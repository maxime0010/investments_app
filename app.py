from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, json, request, current_app
import mysql.connector
import os
import stripe
import logging
from datetime import datetime
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from functools import wraps

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'default_secret_key')

# Stripe configuration
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
YOUR_DOMAIN = os.getenv('YOUR_DOMAIN', 'http://localhost:5000')

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
    def __init__(self, id, email, is_member):
        self.id = id
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
        return User(user['id'], email=user['email'], is_member=user['is_member'])
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

@app.route('/pro')
def membership_pro():
    return render_template('membership_pro.html')

@app.route('/portfolio')
@login_required
def portfolio():
    email = current_user.email
    subscription_status, customer_id, error = get_subscription_status(email)

    if error:
        return render_template('portfolio.html', error=error)
    
    # Update the is_member attribute based on subscription status
    if subscription_status == 'active':
        current_user.is_member = True
    else:
        current_user.is_member = False

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
        cursor.execute("INSERT INTO users (email, password_hash, is_active) VALUES (%s, %s, %s)", 
                       (email, password_hash, False))
        conn.commit()

        # Fetch the newly created user to log them in and send confirmation email
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()

        cursor.close()
        conn.close()

        if user:
            user_obj = User(user['id'], email=user['email'], is_member=False)
            login_user(user_obj)
            
            # Send confirmation email
            send_confirmation_email(email, user['id'])

            flash('A confirmation email has been sent to your inbox. Please confirm your account to proceed.', 'info')
            return redirect(url_for('profile'))

    return render_template('membership_step1.html')



def send_confirmation_email(email, user_id):
    confirmation_url = url_for('confirm_email', user_id=user_id, _external=True)
    subject = "Confirm your account"
    html = render_template('email/confirm.html', confirmation_url=confirmation_url)
    msg = Message(subject, recipients=[email], html=html)
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

@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    try:
        prices = stripe.Price.list(
            lookup_keys=[request.form['lookup_key']],
            expand=['data.product']
        )

        checkout_session = stripe.checkout.Session.create(
            line_items=[
                {
                    'price': prices.data[0].id,
                    'quantity': 1,
                },
            ],
            mode='subscription',
            success_url=YOUR_DOMAIN + '/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=YOUR_DOMAIN + '/cancel',
        )
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        print(f"Error creating checkout session: {e}")
        return str(e), 500




@app.route('/cancel')
def cancel():
    return "Payment was canceled."


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('index'))

@app.route('/profile')
@login_required
def profile():
    # Assume the user's email is stored in current_user.email
    email = current_user.email
    subscription_status, customer_id, error = get_subscription_status(email)

    if error:
        return render_template('profile.html', error=error)

    if not subscription_status:
        # If no subscription is found, redirect to the subscribe route
        return redirect(url_for('subscribe'))

    return render_template('profile.html', subscription_status=subscription_status, customer_id=customer_id)



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
            user_obj = User(user['id'], email=user['email'], is_member=user['is_member'])
            login_user(user_obj)
            return redirect(url_for('index'))
        else:
            flash('Invalid email or password', 'danger')

    return render_template('login.html')



@app.route('/create-portal-session', methods=['POST'])
@login_required
def create_portal_session():
    checkout_session_id = request.form.get('session_id')
    checkout_session = stripe.checkout.Session.retrieve(checkout_session_id)

    # This is the URL to which the customer will be redirected after they are
    # done managing their billing with the portal.
    return_url = YOUR_DOMAIN

    portalSession = stripe.billing_portal.Session.create(
        customer=checkout_session.customer,
        return_url=return_url,
    )
    return redirect(portalSession.url, code=303)



@app.route('/success')
def success():
    session_id = request.args.get('session_id')
    return render_template('success.html', session_id=session_id)

@app.route('/terms-of-service')
def terms_of_service():
    return render_template('terms_of_service.html')

@app.route('/privacy-notice')
def privacy_notice():
    return render_template('privacy_notice.html')

@app.route('/refund-policy')
def refund_policy():
    return render_template('refund_policy.html')

@app.route('/webhook', methods=['POST'])
def webhook_received():
    webhook_secret = os.getenv('STRIPE_WEBHOOK_SECRET')
    request_data = json.loads(request.data)

    if webhook_secret:
        # Retrieve the event by verifying the signature using the raw body and secret if webhook signing is configured.
        signature = request.headers.get('stripe-signature')
        try:
            event = stripe.Webhook.construct_event(
                payload=request.data, sig_header=signature, secret=webhook_secret)
            data = event['data']
        except Exception as e:
            return e
        # Get the type of webhook event sent - used to check the status of PaymentIntents.
        event_type = event['type']
    else:
        data = request_data['data']
        event_type = request_data['type']
    data_object = data['object']

    print('event ' + event_type)

    if event_type == 'checkout.session.completed':
        print('🔔 Payment succeeded!')
    elif event_type == 'customer.subscription.trial_will_end':
        print('Subscription trial will end')
    elif event_type == 'customer.subscription.created':
        print('Subscription created %s', event.id)
    elif event_type == 'customer.subscription.updated':
        print('Subscription created %s', event.id)
    elif event_type == 'customer.subscription.deleted':
        # handle subscription canceled automatically based
        # upon your subscription settings. Or if the user cancels it.
        print('Subscription canceled: %s', event.id)
    elif event_type == 'entitlements.active_entitlement_summary.updated':
        # handle active entitlement summary updated
        print('Active entitlement summary updated: %s', event.id)

    return jsonify({'status': 'success'})


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

# Helper function to get the subscription status using an email address
def get_subscription_status(email):
    try:
        customer_list = stripe.Customer.list(email=email).data
        if not customer_list:
            return None, None, 'No customer found with the provided email address'

        customer_id = customer_list[0].id
        subscriptions = stripe.Subscription.list(customer=customer_id)
        subscription_status = subscriptions.data[0].status if subscriptions.data else None
        return subscription_status, customer_id, None

    except stripe.error.StripeError as e:
        return None, None, str(e)



@app.route('/manage-subscription', methods=['POST'])
@login_required
def manage_subscription():
    customer_id = request.form.get('customer_id')
    if not customer_id:
        return jsonify({'error': 'Customer ID is missing'}), 400
    
    try:
        # Redirect to the Stripe Customer Portal
        return redirect("https://billing.stripe.com/p/login/test_cN29Eq1So5wY52MbII")

    except stripe.error.StripeError as e:
        return jsonify({'error': str(e)}), 400

@app.route('/subscribe', methods=['POST'])
@login_required
def subscribe():
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            customer_email=current_user.email,
            line_items=[{
                'price': 'price_1PrmU5DIMC3D1ZmedUvTdwTf',  # Replace with your actual price ID
                'quantity': 1,
            }],
            mode='subscription',
            success_url=url_for('profile', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('profile', _external=True),
        )
        return redirect(session.url, code=303)

    except stripe.error.StripeError as e:
        return jsonify({'error': str(e)}), 400







updates = [
    {"date": "August 25th, 2024", "title": "Weekly Update: August 25th, 2024", "content": "<p>Details about the update for August 25th, 2024.</p>"},
    {"date": "August 18th, 2024", "title": "Weekly Update: August 18th, 2024", "content": "<p>Details about the update for August 18th, 2024.</p>"},
]

if __name__ == '__main__':
    app.debug = True
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
