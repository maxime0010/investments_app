from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import mysql.connector
import os
import requests
from datetime import datetime
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import stripe
from functools import wraps

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# Stripe configuration
stripe.api_key = os.getenv('STRIPE_SECRET')

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
            return redirect(url_for('membership'))
        return f(*args, **kwargs)
    return decorated_function

def fetch_stock_prices(ticker):
    api_key = "KG8F3YBYGVL0HFFU"
    url = f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY_ADJUSTED&symbol={ticker}&outputsize=compact&apikey={api_key}"
    response = requests.get(url)
    data = response.json()

    # Debug: Print the entire API response to check its structure
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

    # Query to fetch the website URL based on the stock ticker
    cursor.execute("SELECT website FROM stock WHERE ticker = %s", (ticker,))
    result = cursor.fetchone()

    cursor.close()
    conn.close()

    if result and 'website' in result:
        website = result['website']
        # Assuming the website URLs are in the format www.example.com
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

# Portfolio Page Route
@app.route('/portfolio')
def portfolio():
    latest_date = get_latest_portfolio_date()
    top_stocks = get_top_stocks(latest_date)
    return render_template('portfolio.html', stocks=top_stocks, last_updated=latest_date)

# Stock Detail Route
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

    # Fetch stock prices from Alpha Vantage API
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

# Performance Page Route
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

# Subscription Route
@app.route('/subscribe', methods=['POST'])
def subscribe():
    email = request.form['email']

    # Save the email to the database
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

# Membership Page Route
@app.route('/membership')
def membership():
    return render_template('membership.html')

# Create Subscription Route
@app.route('/create-subscription', methods=['POST'])
@login_required
def create_subscription():
    data = request.json

    try:
        customer = stripe.Customer.create(
            payment_method=data['payment_method'],
            email=current_user.email,
            invoice_settings={
                'default_payment_method': data['payment_method'],
            },
        )

        subscription = stripe.Subscription.create(
            customer=customer.id,
            items=[{'price': 'your-price-id'}],  # Replace with your actual price ID
            expand=['latest_invoice.payment_intent'],
        )

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO members (user_id, stripe_customer_id, stripe_subscription_id, subscription_status) VALUES (%s, %s, %s, %s)",
                       (current_user.id, customer.id, subscription.id, subscription.status))
        conn.commit()

        cursor.execute("UPDATE users SET is_member = TRUE WHERE id = %s", (current_user.id,))
        conn.commit()

        cursor.close()
        conn.close()

        return jsonify(subscription)
    except Exception as e:
        return jsonify(error=str(e)), 403

# Weekly Updates Routes
@app.route('/weekly_updates')
def weekly_updates():
    latest_update = updates[0]  # Assuming the latest update is the first in the list
    return render_template('weekly_updates.html', updates=updates, latest_update=latest_update)

@app.route('/weekly_update/<date>')
def update(date):
    selected_update = next((update for update in updates if update["date"] == date), None)
    return render_template('update_detail.html', update=selected_update)

# Index Page Route
@app.route('/')
def index():
    num_reports, num_analysts, num_banks = get_ratings_statistics()
    return render_template('index.html', num_reports=num_reports, num_analysts=num_analysts, num_banks=num_banks)

# Get Ratings Statistics Function
def get_ratings_statistics():
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()

    # Get the number of reports (rows in the ratings table)
    cursor.execute("SELECT COUNT(*) FROM ratings")
    num_reports = cursor.fetchone()[0]

    # Get the number of unique analysts
    cursor.execute("SELECT COUNT(DISTINCT analyst_name) FROM ratings")
    num_analysts = cursor.fetchone()[0]

    # Get the number of unique investment banks
    cursor.execute("SELECT COUNT(DISTINCT analyst) FROM ratings")
    num_banks = cursor.fetchone()[0]

    cursor.close()
    conn.close()

    return num_reports, num_analysts, num_banks

if __name__ == '__main__':
    app.debug = True
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
