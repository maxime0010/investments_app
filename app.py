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
from flask_caching import Cache

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

# Flask-Caching setup with Redis
cache = Cache(app, config={'CACHE_TYPE': 'redis', 'CACHE_DEFAULT_TIMEOUT': 300})

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

def get_latest_simulated_portfolio_date():
    """Retrieve the latest date from the portfolio table."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(date) FROM portfolio")
    latest_date = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return latest_date

def get_simulated_top_stocks(latest_date):
    """Fetch top stocks from portfolio based on the latest date."""
    # Try to retrieve from cache first
    cache_key = f"top_simulated_stocks_{latest_date}"
    top_stocks = cache.get(cache_key)
    
    if not top_stocks:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        query = """
            SELECT ps.ticker, MAX(r.name) as name, ps.total_value AS last_price, 
                   ps.stock_price AS expected_return_combined_criteria, ps.quantity AS num_combined_criteria, 
                   MAX(ps.ranking) as ranking, s.indices
            FROM portfolio ps
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

        # Cache the result
        cache.set(cache_key, top_stocks, timeout=300)  # Cache for 5 minutes

    return top_stocks

@app.route('/portfolio')
@cache.cached(timeout=300)  # Cache the portfolio page for 5 minutes
def portfolio():
    is_member = False

    if current_user.is_authenticated:
        email = current_user.email
        cache_key = f"subscription_status_{email}"
        subscription_status = cache.get(cache_key)

        if not subscription_status:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT email FROM users WHERE id = %s", (current_user.id,))
            user = cursor.fetchone()
            cursor.close()
            conn.close()

            if user:
                subscription_status, customer_id, error = get_subscription_status(user['email'])
                cache.set(cache_key, subscription_status, timeout=300)  # Cache for 5 minutes

        if subscription_status == 'active':
            is_member = True

    latest_date = get_latest_simulated_portfolio_date()
    top_stocks = get_simulated_top_stocks(latest_date)

    return render_template('portfolio.html', stocks=top_stocks, last_updated=latest_date, is_member=is_member)

# Continue with the rest of the code...

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
        FROM portfolio ps
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
