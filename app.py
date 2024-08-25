from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import mysql.connector
import os
from datetime import datetime
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from functools import wraps

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'default_secret_key')

# Flask-Mail configuration
app.config['MAIL_SERVER'] = 'smtp-relay.sendinblue.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('BREVO_EMAIL')
app.config['MAIL_PASSWORD'] = os.getenv('BREVO_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER', 'hello@goodlife.money')

mail = Mail(app)

# Database connection configuration
db_config = {
    'user': 'doadmin',
    'password': os.getenv('MYSQL_MDP'),
    'host': 'db-mysql-nyc3-03005-do-user-4526552-0.h.db.ondigitalocean.com',
    'database': 'defaultdb',
    'port': 25060
}

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, username, email, is_member):
        self.id = id
        self.username = username
        self.email = email
        self.is_member = is_member

    def get_id(self):
        return self.id

@login_manager.user_loader
def load_user(user_id):
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    if user:
        return User(user['id'], user['username'], user['email'], user['is_member'])
    return None

# Decorator to restrict access to members-only content
def members_only(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_member:
            flash('You need to be a member to access this page.', 'warning')
            return redirect(url_for('membership_step1'))
        return f(*args, **kwargs)
    return decorated_function

def fetch_stock_prices(ticker):
    api_key = "KG8F3YBYGVL0HFFU"
    url = f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY_ADJUSTED&symbol={ticker}&outputsize=compact&apikey={api_key}"
    response = requests.get(url)
    data = response.json()

    print("API Response:", data)

    prices = []
    if 'Time Series (Daily)' in data:
        time_series = data['Time Series (Daily)']
        for date, values in time_series.items():
            prices.append({
                'date': date,
                'close': float(values['5. adjusted close'])
            })
    
    return prices

def get_latest_portfolio_date():
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(date) FROM portfolio")
    latest_date = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return latest_date

def get_logo_url(ticker):
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT website FROM stock WHERE ticker = %s", (ticker,))
    result = cursor.fetchone()

    cursor.close()
    conn.close()

    if result and 'website' in result:
        website = result['website']
        domain = website.replace("https://", "").replace("http://", "").split('/')[0]
        return f"https://img.logo.dev/{domain}?token=pk_AH6v4ZrySsaUljPEULQWXw"
    return None

def get_top_stocks(latest_date):
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

    query = """
        SELECT p.ticker, MAX(r.name) as name, a.last_closing_price AS last_price, 
               a.expected_return_combined_criteria, a.num_combined_criteria, MAX(p.ranking) as ranking, 
               MAX(a.avg_combined_criteria) as target_price, s.indices
        FROM portfolio p
        JOIN analysis a ON p.ticker = a.ticker
        JOIN ratings r ON r.ticker = p.ticker
        JOIN stock s ON s.ticker = p.ticker
        WHERE p.date = %s
        GROUP BY p.ticker, a.last_closing_price, a.expected_return_combined_criteria, a.num_combined_criteria, s.indices
        ORDER BY ranking
        LIMIT 10
    """
    cursor.execute(query, (latest_date,))
    top_stocks = cursor.fetchall()

    for stock in top_stocks:
        stock['logo_url'] = get_logo_url(stock['ticker'])

    cursor.close()
    conn.close()
    return top_stocks

@app.route('/portfolio')
def portfolio():
    latest_date = get_latest_portfolio_date()
    top_stocks = get_top_stocks(latest_date)
    return render_template('portfolio.html', stocks=top_stocks, last_updated=latest_date)

@app.route('/stock/<ticker>')
@login_required
@members_only
def stock_detail(ticker):
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

    query = """
        SELECT r.name AS stock_name, a.last_closing_price, a.expected_return, 
               a.num_analysts, p.date, p.total_value
        FROM analysis a
        JOIN portfolio p ON a.ticker = p.ticker
        JOIN ratings r ON a.ticker = r.ticker
        WHERE a.ticker = %s
        ORDER BY p.date DESC
    """
    cursor.execute(query, (ticker,))
    stock_details = cursor.fetchall()

    stock_prices = fetch_stock_prices(ticker)

    cursor.execute("""
        SELECT analyst_name, analyst, adjusted_pt_current, action_company
        FROM ratings
        WHERE ticker = %s
        ORDER BY date DESC
    """, (ticker,))
    analysts = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('stock_detail.html', stock=stock_details, prices=stock_prices, analysts=analysts)

@app.route('/performance')
def performance():
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

    query = """
        SELECT date, SUM(total_value) as total_portfolio_value
        FROM portfolio
        GROUP BY date
        ORDER BY date
    """
    cursor.execute(query)
    performance_data = cursor.fetchall()

    dates = [entry['date'].strftime('%Y-%m-%d') for entry in performance_data if entry['date'] is not None]
    values = [entry['total_portfolio_value'] for entry in performance_data if entry['total_portfolio_value'] is not None]

    if not dates:
        dates = ["No data"]
    if not values:
        values = [0]

    if len(values) >= 30:
        return_30_days = round(((values[-1] - values[-30]) / values[-30]) * 100, 2)
    else:
        return_30_days = None
    
    if len(values) >= 365:
        return_12_months = round(((values[-1] - values[-365]) / values[-365]) * 100, 2)
    else:
        return_12_months = None

    cursor.close()
    conn.close()

    return render_template('performance.html', dates=dates, values=values, 
                           return_30_days=return_30_days, return_12_months=return_12_months)

@app.route('/subscribe', methods=['POST'])
def subscribe():
    email = request.form['email']

    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()

    try:
        cursor.execute("INSERT INTO subscriptions (email) VALUES (%s)", (email,))
        conn.commit()
        flash('Thank you for subscribing to our newsletter!', 'success')
    except mysql.connector.Error as err:
        flash(f"An error occurred: {err}", 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('portfolio'))

@app.route('/membership-step1', methods=['GET', 'POST'])
def membership_step1():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        password_hash = generate_password_hash(password)

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # Check if the email is already registered
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        existing_user = cursor.fetchone()

        if existing_user:
            flash('Email is already registered. Please sign in.', 'danger')
            return redirect(url_for('login'))

        # Insert new user into the database
        cursor.execute("INSERT INTO users (email, password_hash) VALUES (%s, %s)", (email, password_hash))
        conn.commit()

        # Fetch the newly created user to log them in
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()

        cursor.close()
        conn.close()

        if user:
            user_obj = User(user['id'], email=user['email'], username=user['email'], is_member=user['is_member'])
            login_user(user_obj)
            return redirect(url_for('membership_step2'))

    return render_template('membership_step1.html')


def send_confirmation_email(email, user_id):
    confirmation_url = url_for('confirm_email', user_id=user_id, _external=True)
    subject = "Confirm your account"
    html = render_template('email/confirm.html', confirmation_url=confirmation_url)
    msg = Message(subject, recipients=[email], html=html, sender=os.getenv('MAIL_DEFAULT_SENDER', 'hello@goodlife.money'))
    mail.send(msg)

@app.route('/confirm/<int:user_id>')
def confirm_email(user_id):
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()

    cursor.execute("UPDATE users SET is_active = TRUE WHERE id = %s", (user_id,))
    conn.commit()

    cursor.close()
    conn.close()

    flash('Your account has been confirmed. Please log in.', 'success')
    return redirect(url_for('login'))

@app.route('/membership-step2')
@login_required
def membership_step2():
    return render_template('membership_step2.html')

@app.route('/paddle-webhook', methods=['POST'])
def paddle_webhook():
    data = request.form.to_dict()

    if data['alert_name'] == 'subscription_created':
        user_id = int(data['passthrough'])
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET is_member = TRUE WHERE id = %s", (user_id,))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'status': 'success'})

    return jsonify({'status': 'ignored'})

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('index'))

@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html')

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email']

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()

        if user:
            send_reset_password_email(user['email'], user['id'])
            flash('A password reset link has been sent to your email.', 'success')
        else:
            flash('No account found with that email.', 'danger')

        cursor.close()
        conn.close()

    return render_template('forgot_password.html')

def send_reset_password_email(email, user_id):
    reset_url = url_for('reset_password', user_id=user_id, _external=True)
    subject = "Reset your password"
    html = render_template('email/reset_password.html', reset_url=reset_url)
    msg = Message(subject, recipients=[email], html=html)
    mail.send(msg)

@app.route('/reset-password/<int:user_id>', methods=['GET', 'POST'])
def reset_password(user_id):
    if request.method == 'POST':
        password = request.form['password']
        password_hash = generate_password_hash(password)

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET password_hash = %s WHERE id = %s", (password_hash, user_id))
        conn.commit()

        cursor.close()
        conn.close()

        flash('Your password has been reset. Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('reset_password.html', user_id=user_id)

@app.route('/weekly_updates')
def weekly_updates():
    latest_update = updates[0]
    return render_template('weekly_updates.html', updates=updates, latest_update=latest_update)

@app.route('/weekly_update/<date>')
def update(date):
    selected_update = next((update for update in updates if update["date"] == date), None)
    return render_template('update_detail.html', update=selected_update)

@app.route('/')
def index():
    num_reports, num_analysts, num_banks = get_ratings_statistics()
    return render_template('index.html', num_reports=num_reports, num_analysts=num_analysts, num_banks=num_banks)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user and check_password_hash(user['password_hash'], password):
            user_obj = User(user['id'], user['username'], user['email'], user['is_member'])
            login_user(user_obj)
            return redirect(url_for('index'))
        else:
            flash('Invalid email or password', 'danger')

    return render_template('login.html')

@app.route('/terms-of-service')
def terms_of_service():
    return render_template('terms_of_service.html')

@app.route('/privacy-notice')
def privacy_notice():
    return render_template('privacy_notice.html')

@app.route('/refund-policy')
def refund_policy():
    return render_template('refund_policy.html')

def get_ratings_statistics():
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM ratings")
    num_reports = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT analyst_name) FROM ratings")
    num_analysts = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT analyst) FROM ratings")
    num_banks = cursor.fetchone()[0]

    cursor.close()
    conn.close()

    return num_reports, num_analysts, num_banks

updates = [
    {"date": "August 25th, 2024", "title": "Weekly Update: August 25th, 2024", "content": "<p>Details about the update for August 25th, 2024.</p>"},
    {"date": "August 18th, 2024", "title": "Weekly Update: August 18th, 2024", "content": "<p>Details about the update for August 18th, 2024.</p>"},
]

if __name__ == '__main__':
    app.debug = True
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
