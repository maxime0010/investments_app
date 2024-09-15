from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, current_app
import mysql.connector
from mysql.connector import pooling
import os
import stripe
import requests
from datetime import datetime, timedelta
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from functools import wraps

# Flask configuration
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

# Database connection pooling configuration
db_pool = pooling.MySQLConnectionPool(pool_name="mypool", pool_size=5, **{
    'user': 'doadmin',
    'password': os.getenv('MYSQL_MDP'),
    'host': os.getenv('MYSQL_HOST'),
    'database': 'defaultdb',
    'port': 25060
})

# Helper function for database connection
def get_db_connection():
    try:
        conn = db_pool.get_connection()
        return conn
    except mysql.connector.Error as err:
        print(f"Error: {err}")
        return None

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
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    if user:
        return User(user['id'], email=user['email'], is_member=user['is_member'])
    return None

# Helper function to calculate annualized return
def calculate_annualized_return(start_value, end_value, start_date, end_date):
    days_difference = (end_date - start_date).days
    years_difference = days_difference / 365.25  # Account for leap years
    if years_difference == 0:
        return 0
    return ((end_value / start_value) ** (1 / years_difference)) - 1

# Decorator to restrict access to members-only content
def members_only(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_member:
            flash('You need to be a member to access this page.', 'warning')
            return redirect(url_for('membership_step1'))
        return f(*args, **kwargs)
    return decorated_function

# Stripe-related functionality omitted for brevity. Include your Stripe routes as needed.

# Simulated Portfolio Functions

def get_latest_simulated_portfolio_date():
    """Retrieve the latest date from the portfolio_simulation table."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(date) FROM portfolio_simulation")
    latest_date = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return latest_date

def get_simulated_top_stocks(latest_date):
    """Fetch top stocks from portfolio_simulation based on the latest date."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    query = """
        SELECT ps.ticker, MAX(r.name) as name, ps.total_value AS last_price, 
               ps.stock_price AS expected_return_combined_criteria, ps.quantity AS num_combined_criteria, 
               MAX(ps.ranking) as ranking, s.indices
        FROM portfolio_simulation ps
        JOIN ratings r ON r.ticker = ps.ticker
        JOIN stock s ON s.ticker = ps.ticker
        WHERE ps.date = %s
        GROUP BY ps.ticker, ps.total_value, ps.stock_price, ps.quantity, s.indices
        ORDER BY ranking
        LIMIT 10
    """
    cursor.execute(query, (latest_date,))
    top_stocks = cursor.fetchall()

    cursor.close()
    conn.close()

    return top_stocks

@app.route('/portfolio')
def portfolio():
    is_member = False

    if current_user.is_authenticated:
        email = current_user.email

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT email FROM users WHERE id = %s", (current_user.id,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user:
            subscription_status, customer_id, error = get_subscription_status(user['email'])

        if subscription_status == 'active':
            is_member = True

    latest_date = get_latest_simulated_portfolio_date()
    top_stocks = get_simulated_top_stocks(latest_date)

    return render_template('portfolio.html', stocks=top_stocks, last_updated=latest_date, is_member=is_member)

@app.route('/performance')
def performance():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Fetch simulated portfolio values and S&P 500 data
    cursor.execute("""
        SELECT ps.date, ps.total_value AS total_portfolio_value, 
               (SELECT close 
                FROM prices sp 
                WHERE sp.ticker = 'SPX' AND sp.date <= ps.date 
                ORDER BY sp.date DESC LIMIT 1) AS sp500_value
        FROM portfolio_simulation ps
        ORDER BY ps.date
    """)
    simulated_portfolio_data = cursor.fetchall()

    cursor.close()
    conn.close()

    # Extract data for chart display
    dates_simulation = [row['date'].strftime('%Y-%m-%d') for row in simulated_portfolio_data]
    simulated_portfolio_values = [row['total_portfolio_value'] for row in simulated_portfolio_data]
    sp500_values_simulation = [row['sp500_value'] for row in simulated_portfolio_data]

    return render_template('performance.html', 
                           dates_simulation=dates_simulation, 
                           simulation_values=simulated_portfolio_values, 
                           sp500_values_simulation=sp500_values_simulation)

# User Management and Authentication Routes

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = get_db_connection()
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

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('index'))

@app.route('/membership-step1', methods=['GET', 'POST'])
def membership_step1():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        password_hash = generate_password_hash(password)

        conn = get_db_connection()
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
            user_obj = User(user['id'], email=user['email'], is_member=user['is_member'])
            login_user(user_obj)
            return redirect(url_for('membership_step2'))

    return render_template('membership_step1.html')

@app.route('/profile')
@login_required
def profile():
    email = current_user.email
    subscription_status, customer_id, error = get_subscription_status(email)

    if error:
        return render_template('profile.html', error=error)

    if not subscription_status:
        return redirect(url_for('subscribe'))

    return render_template('profile.html', email=email, subscription_status=subscription_status, customer_id=customer_id)

@app.route('/subscribe', methods=['POST'])
@login_required
def subscribe():
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            customer_email=current_user.email,
            line_items=[{
                'price': os.getenv('STRIPE_PRICE_ID'),  # Replace with your actual price ID
                'quantity': 1,
            }],
            mode='subscription',
            success_url=url_for('profile', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('profile', _external=True),
        )
        return redirect(session.url, code=303)

    except stripe.error.StripeError as e:
        return jsonify({'error': str(e)}), 400

@app.route('/coverage')
def coverage():
    is_member = False

    if current_user.is_authenticated:
        # Retrieve the email from the database using the user ID
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT email FROM users WHERE id = %s", (current_user.id,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user:
            email = user['email']
            subscription_status, customer_id, error = get_subscription_status(email)

            if subscription_status == 'active':
                is_member = True

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    query = """
        SELECT s.name AS stock_name, a.ticker, s.indices, a.last_closing_price,
               a.average_price_target,  
               a.avg_combined_criteria,  
               a.num_analysts, a.num_recent_analysts, a.num_high_success_analysts,
               a.expected_return_combined_criteria
        FROM analysis a
        JOIN stock s ON a.ticker = s.ticker
        ORDER BY s.name ASC
    """
    cursor.execute(query)
    coverage_data = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('coverage.html', coverage_data=coverage_data)

# Helper Functions for Stripe and Subscription Handling

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

# Error handling and additional utility routes omitted for brevity

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
