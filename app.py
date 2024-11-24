from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, json, request, current_app, make_response
import mysql.connector
import os
import stripe
import logging
import requests
from datetime import datetime, timedelta
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from functools import wraps
from mysql.connector import Error
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from itsdangerous import URLSafeTimedSerializer
from alpaca_client import create_account  # Import the backend function

# Helper function to calculate annualized return
def calculate_annualized_return(start_value, end_value, start_date, end_date):
    # Calculate the time difference in years
    days_difference = (end_date - start_date).days
    years_difference = days_difference / 365.25  # Account for leap years

    # Avoid division by zero for very short periods
    if years_difference == 0:
        return 0

    # Calculate the annualized return
    return ((end_value / start_value) ** (1 / years_difference)) - 1
    
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'default_secret_key')

# Initialize the serializer for generating and verifying tokens
serializer = URLSafeTimedSerializer(app.secret_key)

# Stripe configuration
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
YOUR_DOMAIN = os.getenv('YOUR_DOMAIN', 'http://localhost:5000')

# Flask-Mail configuration
app.config['MAIL_SERVER'] = 'smtp-relay.brevo.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('BREVO_EMAIL')
app.config['MAIL_PASSWORD'] = os.getenv('BREVO_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER', 'hello@goodlife.money')

mail = Mail(app)

# Retrieve MySQL password from environment variables
mdp = os.getenv("MYSQL_MDP")
if not mdp:
    raise ValueError("No MySQL password found in environment variables")
host = os.getenv("MYSQL_HOST")
if not host:
    raise ValueError("No Host found in environment variables")
    
# Database connection configuration
db_config = {
    'user': 'doadmin',
    'password': mdp,
    'host': host,
    'database': 'defaultdb',
    'port': 25060
}

def get_db_connection():
    try:
        # Reconnect if connection is lost or doesn't exist
        conn = mysql.connector.connect(**db_config)
        if conn.is_connected():
            return conn
        else:
            raise mysql.connector.Error("Failed to connect to the database.")
    except Error as err:
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
    cursor.execute("SELECT MAX(date) FROM portfolio365")
    latest_date = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return latest_date

def get_logo_url(ticker):
    # Use the Logo.dev API to fetch logos using the ticker symbol
    public_token = "pk_AH6v4ZrySsaUljPEULQWXw"  # Replace with your actual public token from Logo.dev
    return f"https://img.logo.dev/ticker/{ticker}?token={public_token}"

def get_top_stocks(latest_date):
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

    query = """
        SELECT p.ticker, MAX(r.name) as name, a.last_closing_price AS last_price, 
               a.expected_return_combined_criteria, a.num_combined_criteria, MAX(p.ranking) as ranking, 
               MAX(a.avg_combined_criteria) as target_price, s.indices
        FROM portfolio365 p
        JOIN analysis10 a ON p.ticker = a.ticker
        JOIN ratings r ON r.ticker = p.ticker
        JOIN stock s ON s.ticker = p.ticker
        WHERE p.date = %s AND a.date = %s
        GROUP BY p.ticker, a.last_closing_price, a.expected_return_combined_criteria, a.num_combined_criteria, s.indices
        ORDER BY ranking
        LIMIT 20
    """
    cursor.execute(query, (latest_date, latest_date))
    top_stocks = cursor.fetchall()

    # Add logo URLs to the stocks
    for stock in top_stocks:
        stock['logo_url'] = get_logo_url(stock['ticker'])

    cursor.close()
    conn.close()
    return top_stocks

    if not top_stocks:
        flash('No stocks found for the selected date. Please try again later.', 'warning')


@app.route('/pro')
def membership_pro():
    # Render the membership_pro.html template without any extra unused variables
    return render_template('membership_pro.html')



@app.route('/portfolio')
def portfolio():
    is_member = False

    if current_user.is_authenticated:
        # Retrieve the email from the database using the user ID
        conn = mysql.connector.connect(**db_config)
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

    latest_date = get_latest_portfolio_date()
    top_stocks = get_top_stocks(latest_date)

    return render_template('portfolio.html', stocks=top_stocks, last_updated=latest_date, is_member=is_member)


@app.route('/stock/<ticker>')
def stock_detail(ticker):
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

    try:
        # Fetch the stock name from the 'stock' table
        cursor.execute("""
            SELECT name
            FROM stock
            WHERE ticker = %s
            LIMIT 1
        """, (ticker,))
        stock_name_result = cursor.fetchone()
        stock_name = stock_name_result['name'] if stock_name_result else "Unknown Stock"

        # Fetch the logo URL for the company
        logo_url = get_logo_url(ticker)

        # Fetch the most recent analysis data for the stock
        cursor.execute("""
            SELECT last_closing_price, avg_combined_criteria, expected_return_combined_criteria
            FROM analysis10
            WHERE ticker = %s
            ORDER BY date DESC
            LIMIT 1
        """, (ticker,))
        analysis_data = cursor.fetchone()

        if not analysis_data:
            analysis_data = {
                'last_closing_price': "N/A",
                'avg_combined_criteria': "N/A",
                'expected_return_combined_criteria': "N/A"
            }

        # Convert decimal.Decimal values to float
        analysis_data['last_closing_price'] = float(analysis_data['last_closing_price']) if analysis_data['last_closing_price'] else None
        analysis_data['avg_combined_criteria'] = float(analysis_data['avg_combined_criteria']) if analysis_data['avg_combined_criteria'] else None
        analysis_data['expected_return_combined_criteria'] = float(analysis_data['expected_return_combined_criteria']) if analysis_data['expected_return_combined_criteria'] else None

        # Check if the stock is in the latest version of the portfolio
        latest_date = get_latest_portfolio_date()
        cursor.execute("""
            SELECT ticker
            FROM portfolio365
            WHERE ticker = %s AND date = %s
        """, (ticker, latest_date))
        stock_in_portfolio = cursor.fetchone() is not None

        # Fetch SWOT analysis from InvestmentReports (including the `id`)
        cursor.execute("""
            SELECT id, dimension, question, answer
            FROM InvestmentReports
            WHERE ticker = %s
            ORDER BY date DESC
        """, (ticker,))
        swot_data = cursor.fetchall()

        swot_reports = {
            'strengths': [report for report in swot_data if report['dimension'] == 'Strengths'],
            'weaknesses': [report for report in swot_data if report['dimension'] == 'Weaknesses'],
            'opportunities': [report for report in swot_data if report['dimension'] == 'Opportunities'],
            'risks': [report for report in swot_data if report['dimension'] == 'Risks']
        }

        # Fetch short and long recommendations from the chatgpt table for Strategic Rationale
        cursor.execute("""
            SELECT short_recommendation, long_recommendation
            FROM chatgpt
            WHERE ticker = %s
            ORDER BY date DESC
            LIMIT 1
        """, (ticker,))
        recommendation_data = cursor.fetchone()

        if recommendation_data:
            analysis_data['short_recommendation'] = recommendation_data['short_recommendation']
            analysis_data['long_recommendation'] = recommendation_data['long_recommendation']
        else:
            analysis_data['short_recommendation'] = "No short recommendation available."
            analysis_data['long_recommendation'] = "No long recommendation available."

        # Fetch analysts' ratings
        cursor.execute("""
            SELECT r.analyst_name, r.analyst AS bank, r.adjusted_pt_current AS price_target, 
                   r.date AS last_update, a.overall_success_rate,
                   (r.date >= CURDATE() - INTERVAL 30 DAY) AS updated_last_30_days,
                   (a.overall_success_rate > %s) AS is_top_performer
            FROM ratings r
            JOIN analysts a ON r.analyst_name = a.name_full
            WHERE r.ticker = %s AND r.date = (
                SELECT MAX(r2.date)
                FROM ratings r2
                WHERE r2.analyst_name = r.analyst_name AND r2.ticker = r.ticker
            )
            ORDER BY r.date DESC, r.analyst_name ASC
        """, (50, ticker))  # Assuming top performers are those with a success rate above 50%
        analysts_data = cursor.fetchall()

        # Calculate expected return for each analyst
        for analyst in analysts_data:
            analyst['price_target'] = float(analyst['price_target']) if analyst['price_target'] else None
            if analyst['price_target'] is not None and analysis_data['last_closing_price'] is not None:
                analyst['expected_return'] = ((analyst['price_target'] - analysis_data['last_closing_price']) / analysis_data['last_closing_price']) * 100
            else:
                analyst['expected_return'] = None  # Handle missing or invalid data

    finally:
        cursor.close()
        conn.close()

    return render_template('stock_detail.html', 
                           ticker=ticker, 
                           stock_name=stock_name,  
                           logo_url=logo_url,    
                           analysis_data=analysis_data, @app.route('/')
def index():
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

    # Fetch portfolio and S&P 500 data from `portfolio365` for simulation
    cursor.execute("""
        SELECT p.date, p.total_value AS total_portfolio_value, 
               (SELECT close 
                FROM prices sp 
                WHERE sp.ticker = 'SPX' AND sp.date <= p.date 
                ORDER BY sp.date DESC LIMIT 1) AS sp500_value
        FROM portfolio365 p
        ORDER BY p.date
    """)
    portfolio_data = cursor.fetchall()

    cursor.close()
    conn.close()

    # Extract data for charts
    dates_simulation = [row['date'].strftime('%Y-%m-%d') for row in portfolio_data]
    simulation_values = [row['total_portfolio_value'] for row in portfolio_data]
    sp500_values_simulation = [row['sp500_value'] for row in portfolio_data]

    # Calculate annualized returns for 10y, 3y, 12m using the helper function
    def fetch_annualized_data(period_days):
        end_date = datetime.strptime(dates_simulation[-1], '%Y-%m-%d')
        start_date = end_date - timedelta(days=period_days)
        filtered_dates, filtered_portfolio, filtered_sp500 = [], [], []
        for date, portfolio, sp500 in zip(dates_simulation, simulation_values, sp500_values_simulation):
            date_obj = datetime.strptime(date, '%Y-%m-%d')
            if date_obj >= start_date:
                filtered_dates.append(date)
                filtered_portfolio.append(portfolio)
                filtered_sp500.append(sp500)
        if len(filtered_portfolio) > 1:
            portfolio_return = calculate_annualized_return(filtered_portfolio[0], filtered_portfolio[-1], start_date, end_date)
            sp500_return = calculate_annualized_return(filtered_sp500[0], filtered_sp500[-1], start_date, end_date)
            return round(portfolio_return * 100, 1), round(sp500_return * 100, 1)
        return 0, 0

    annualized_returns = {
        "10years": fetch_annualized_data(365 * 10),
        "3years": fetch_annualized_data(365 * 3),
        "12months": fetch_annualized_data(365),
    }

    return render_template(
        'index.html',
        dates_simulation=dates_simulation,
        simulation_values=simulation_values,
        sp500_values_simulation=sp500_values_simulation,
        annualized_returns=annualized_returns
    )

                           stock_in_portfolio=stock_in_portfolio, 
                           swot_reports=swot_reports,  # Pass SWOT reports to the template
                           analysts_data=analysts_data)  # Pass analysts' data to the template



@app.route('/answer/<int:question_id>')
def view_answer(question_id):
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

    # Fetch the question, answer, and ticker based on question_id
    cursor.execute("""
        SELECT question, answer, ticker
        FROM InvestmentReports
        WHERE id = %s
        LIMIT 1
    """, (question_id,))
    question_data = cursor.fetchone()

    # Fetch company name and logo URL based on the ticker
    if question_data:
        ticker = question_data['ticker']
        cursor.execute("""
            SELECT name
            FROM stock
            WHERE ticker = %s
            LIMIT 1
        """, (ticker,))
        stock_data = cursor.fetchone()

        company_name = stock_data['name'] if stock_data else "Unknown Company"
        logo_url = get_logo_url(ticker)  # Assuming get_logo_url() is defined to fetch the logo URL

        cursor.close()
        conn.close()

        return render_template('view_answer.html', 
                               question_data=question_data, 
                               company_name=company_name, 
                               logo_url=logo_url, 
                               ticker=ticker)
    else:
        cursor.close()
        conn.close()
        return "Question not found.", 404



@app.route('/membership-step1', methods=['GET', 'POST'])
def membership_step1():
    # If the user is already logged in, redirect to membership_step2
    if current_user.is_authenticated:
        return redirect(url_for('membership_step2'))
    
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
            # Check if the user has already set a password
            if existing_user['password_hash']:
                # Password is already set, redirect to login
                flash('Email is already registered. Please sign in.', 'danger')
                return redirect(url_for('login', email=email))
            else:
                # Password is not set, so update the user with the new password
                cursor.execute("UPDATE users SET password_hash = %s WHERE email = %s", (password_hash, email))
                conn.commit()

                # Fetch the updated user and log them in
                cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
                user = cursor.fetchone()

                cursor.close()
                conn.close()

                if user:
                    user_obj = User(user['id'], email=user['email'], is_member=user['is_member'])
                    login_user(user_obj)
                    return redirect(url_for('membership_step2'))

        else:
            # Insert new user into the database if the email doesn't exist
            cursor.execute("INSERT INTO users (email, password_hash) VALUES (%s, %s)", (email, password_hash))
            conn.commit()

            # Fetch the newly created user and log them in
            cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
            user = cursor.fetchone()

            cursor.close()
            conn.close()

            if user:
                user_obj = User(user['id'], email=user['email'], is_member=user['is_member'])
                login_user(user_obj)
                return redirect(url_for('membership_step2'))

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
    try:
        # Create a checkout session directly when the user hits this route
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            customer_email=current_user.email,  # Use the current user's email for Stripe checkout
            line_items=[{
                'price': os.getenv('STRIPE_PRICE_ID'),  # Replace with your actual Stripe price ID
                'quantity': 1,
            }],
            mode='subscription',
            allow_promotion_codes=True,
            success_url=url_for('success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('cancel', _external=True),
        )
        # Redirect user directly to Stripe's checkout page
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        print(f"Error creating checkout session: {e}")
        return str(e), 500



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
                    'price': os.getenv('STRIPE_PRICE_ID'),
                    'quantity': 1,
                },
            ],
            mode='subscription',
            allow_promotion_codes=True,
            success_url=YOUR_DOMAIN + '/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=YOUR_DOMAIN + '/cancel',
        )
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        print(f"Error creating checkout session: {e}")
        return str(e), 500





@app.route('/cancel')
def cancel():
    return render_template('cancel.html')



@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('index'))

@app.route('/profile')
@login_required
def profile():

    email=current_user.email,
    subscription_status, customer_id, error = get_subscription_status(email)

    if error:
        return render_template('profile.html', error=error)

    if not subscription_status:
        # If no subscription is found, redirect to the subscribe route
        return redirect(url_for('subscribe'))

    return render_template('profile.html', email=email, subscription_status=subscription_status, customer_id=customer_id)


# Initialize Brevo (Sendinblue) configuration
def setup_brevo_api():
    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key['api-key'] = os.getenv('BREVO_API_KEY')  # Ensure you are using environment variables
    return sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))


def send_reset_password_email(user_email, reset_url):
    # Setting up Brevo API client
    api_instance = setup_brevo_api()
    subject = "Reset your Good Life Password"
    sender = {"name": "Good Life 💵 Support", "email": "hello@goodlife.money"}
    receivers = [{"email": user_email}]
    
    # Email content
    content = f"""
    <h3>Password Reset Request</h3>
    <p>Please click the link below to reset your password:</p>
    <a href="{reset_url}">{reset_url}</a>
    <p>This link will expire in 1 hour.</p>
    """

    # Build the email object
    email = sib_api_v3_sdk.SendSmtpEmail(
        to=receivers,
        sender=sender,
        subject=subject,
        html_content=content,
        
    )
    
    try:
        # Attempt to send the email
        print(f"Sending email to: {user_email}")
        response = api_instance.send_transac_email(email)
        print(f"Email sent successfully: {response}")
    except ApiException as e:
        print(f"Failed to send email: {e}")
        raise



@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email']
        print(f"Processing forgot password for email: {email}")  # Debugging print

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user:
            print(f"User found: {user}")  # Debugging print

            # Generate the token
            token = serializer.dumps(user['id'], salt='password-reset-salt')
            reset_url = url_for('reset_password', token=token, _external=True)
            print(f"Reset URL: {reset_url}")  # Debugging print
            
            # Send the reset email
            send_reset_password_email(email, reset_url)
            flash('A password reset link has been sent to your email.', 'success')
        else:
            print(f"No user found with email: {email}")  # Debugging print
            flash('No account found with that email.', 'danger')

    return render_template('forgot_password.html')


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        user_id = serializer.loads(token, salt='password-reset-salt', max_age=3600)
        print(f"Token valid for user ID: {user_id}")  # Debugging print
    except Exception as e:
        flash('The reset link is invalid or has expired.', 'danger')
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        new_password = request.form['password']
        password_hash = generate_password_hash(new_password)
        print(f"New password set for user ID: {user_id}")  # Debugging print

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET password_hash = %s WHERE id = %s", (password_hash, user_id))
        conn.commit()
        cursor.close()
        conn.close()

        flash('Your password has been updated. Please log in.', 'success')
        return redirect(url_for('login'))

    # Pass the token to the template
    return render_template('reset_password.html', token=token)



@app.route('/weekly_updates')
def weekly_updates():
    # Example list of updates
    updates = [
        {"date": "2024-09-01", "title": "Newsletter #1 - Week of Sept 1st"},
        {"date": "2024-09-08", "title": "Newsletter #2 - Week of Sept 8th"},
        {"date": "2024-09-15", "title": "Newsletter #3 - Week of Sept 15th"}
    ]

    # Determine if the user is a member
    is_member = False

    if current_user.is_authenticated:
        # Retrieve the email from the database using the user ID
        conn = mysql.connector.connect(**db_config)
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

    # Render the template with the updates and membership status
    return render_template('weekly_newsletter.html', updates=updates, is_member=is_member)


@app.route('/weekly_update/<date>')
def view_newsletter(date):
    try:
        return render_template(f'newsletters/{date}.html')
    except Exception as e:
        return render_template('404.html'), 404  # Render a 404 page if the newsletter doesn't exist


@app.route('/')
def index():
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

    # Fetch portfolio and S&P 500 data from `portfolio365` for simulation
    cursor.execute("""
        SELECT p.date, p.total_value AS total_portfolio_value, 
               (SELECT close 
                FROM prices sp 
                WHERE sp.ticker = 'SPX' AND sp.date <= p.date 
                ORDER BY sp.date DESC LIMIT 1) AS sp500_value
        FROM portfolio365 p
        ORDER BY p.date
    """)
    portfolio_data = cursor.fetchall()

    cursor.close()
    conn.close()

    # Extract data for charts
    dates_simulation = [row['date'].strftime('%Y-%m-%d') for row in portfolio_data]
    simulation_values = [row['total_portfolio_value'] for row in portfolio_data]
    sp500_values_simulation = [row['sp500_value'] for row in portfolio_data]

    # Calculate annualized returns for 10y, 3y, 12m using the helper function
    def fetch_annualized_data(period_days):
        end_date = datetime.strptime(dates_simulation[-1], '%Y-%m-%d')
        start_date = end_date - timedelta(days=period_days)
        filtered_dates, filtered_portfolio, filtered_sp500 = [], [], []
        for date, portfolio, sp500 in zip(dates_simulation, simulation_values, sp500_values_simulation):
            date_obj = datetime.strptime(date, '%Y-%m-%d')
            if date_obj >= start_date:
                filtered_dates.append(date)
                filtered_portfolio.append(portfolio)
                filtered_sp500.append(sp500)
        if len(filtered_portfolio) > 1:
            portfolio_return = calculate_annualized_return(filtered_portfolio[0], filtered_portfolio[-1], start_date, end_date)
            sp500_return = calculate_annualized_return(filtered_sp500[0], filtered_sp500[-1], start_date, end_date)
            return round(portfolio_return * 100, 1), round(sp500_return * 100, 1)
        return 0, 0

    annualized_returns = {
        "10years": fetch_annualized_data(365 * 10),
        "3years": fetch_annualized_data(365 * 3),
        "12months": fetch_annualized_data(365),
    }

    return render_template(
        'index.html',
        dates_simulation=dates_simulation,
        simulation_values=simulation_values,
        sp500_values_simulation=sp500_values_simulation,
        annualized_returns=annualized_returns
    )

    

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
        conn = mysql.connector.connect(**db_config)
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

    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

    # Step 1: Fetch the most recent date from analysis10 table
    cursor.execute("SELECT MAX(date) AS latest_date FROM analysis10")
    latest_date = cursor.fetchone()['latest_date']

    # Step 2: Fetch stocks only for the latest date
    query = """
        SELECT s.name AS stock_name, a.ticker, s.indices, a.last_closing_price,
               a.average_price_target,  
               a.avg_combined_criteria,  
               a.num_analysts, a.num_recent_analysts, a.num_high_success_analysts,
               a.expected_return_combined_criteria
        FROM analysis10 a
        JOIN stock s ON a.ticker = s.ticker
        WHERE a.date = %s  -- Only select records from the most recent date
        ORDER BY s.name ASC
    """
    cursor.execute(query, (latest_date,))
    coverage_data = cursor.fetchall()

    # Fetch the logo URLs and add them to each stock
    for stock in coverage_data:
        stock['logo_url'] = get_logo_url(stock['ticker'])

    # Query to fetch the most recent update date from the ratings table
    cursor.execute("SELECT MAX(date) AS last_updated FROM ratings")
    last_updated = cursor.fetchone()['last_updated']

    cursor.close()
    conn.close()

    # Filter out stocks with last_closing_price as None or 0, and round all numbers
    filtered_coverage_data = []
    for stock in coverage_data:
        if stock['last_closing_price'] is None or stock['last_closing_price'] == 0:
            continue
        
        # Replace None with 0 before rounding
        stock['last_closing_price'] = round(stock.get('last_closing_price') or 0)
        stock['average_price_target'] = round(stock.get('average_price_target') or 0)
        stock['avg_combined_criteria'] = round(stock.get('avg_combined_criteria') or 0)
        stock['expected_return_combined_criteria'] = round(stock.get('expected_return_combined_criteria') or 0)
        stock['num_analysts'] = round(stock.get('num_analysts') or 0)
        stock['num_recent_analysts'] = round(stock.get('num_recent_analysts') or 0)
        stock['num_high_success_analysts'] = round(stock.get('num_high_success_analysts') or 0)

        filtered_coverage_data.append(stock)

    num_stocks = len(filtered_coverage_data)

    return render_template('coverage.html', 
                           coverage_data=filtered_coverage_data, 
                           num_stocks=num_stocks, 
                           last_updated=last_updated, 
                           recent_days='30', 
                           is_member=is_member)

    
@app.route('/stock_simulation/<ticker>')
def stock_simulation(ticker):
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

    # Fetch the unique tickers for the dropdown
    cursor.execute("SELECT DISTINCT ticker FROM analysis10 ORDER BY ticker")
    tickers = [row['ticker'] for row in cursor.fetchall()]

    # Fetch stock prices and price targets from the analysis10 table
    cursor.execute("""
        SELECT date, last_closing_price, avg_combined_criteria
        FROM analysis10
        WHERE ticker = %s AND date >= '2019-09-01' AND last_closing_price > 0 AND avg_combined_criteria > 0
        ORDER BY date
    """, (ticker,))
    data = cursor.fetchall()

    cursor.close()
    conn.close()

    # Extract dates, stock prices, and price targets
    dates = [row['date'].strftime('%Y-%m-%d') for row in data]
    stock_prices = [row['last_closing_price'] for row in data]
    price_targets = [row['avg_combined_criteria'] for row in data]

    return render_template('stock_simulation.html', 
                           tickers=tickers, 
                           selected_ticker=ticker, 
                           stock_prices=stock_prices, 
                           price_targets=price_targets, 
                           dates=dates)

@app.route('/data')
def data_overview():
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

    # Fetch the number of analyst ratings for each year from 2013 to 2024
    query_ratings = """
        SELECT r.ticker,
               SUM(CASE WHEN YEAR(r.date) = 2013 THEN 1 ELSE 0 END) AS ratings_2013,
               SUM(CASE WHEN YEAR(r.date) = 2014 THEN 1 ELSE 0 END) AS ratings_2014,
               SUM(CASE WHEN YEAR(r.date) = 2015 THEN 1 ELSE 0 END) AS ratings_2015,
               SUM(CASE WHEN YEAR(r.date) = 2016 THEN 1 ELSE 0 END) AS ratings_2016,
               SUM(CASE WHEN YEAR(r.date) = 2017 THEN 1 ELSE 0 END) AS ratings_2017,
               SUM(CASE WHEN YEAR(r.date) = 2018 THEN 1 ELSE 0 END) AS ratings_2018,
               SUM(CASE WHEN YEAR(r.date) = 2019 THEN 1 ELSE 0 END) AS ratings_2019,
               SUM(CASE WHEN YEAR(r.date) = 2020 THEN 1 ELSE 0 END) AS ratings_2020,
               SUM(CASE WHEN YEAR(r.date) = 2021 THEN 1 ELSE 0 END) AS ratings_2021,
               SUM(CASE WHEN YEAR(r.date) = 2022 THEN 1 ELSE 0 END) AS ratings_2022,
               SUM(CASE WHEN YEAR(r.date) = 2023 THEN 1 ELSE 0 END) AS ratings_2023,
               SUM(CASE WHEN YEAR(r.date) = 2024 THEN 1 ELSE 0 END) AS ratings_2024
        FROM ratings r
        GROUP BY r.ticker
    """
    cursor.execute(query_ratings)
    ratings_data = cursor.fetchall()

    # Fetch the number of stock prices for each year from 2013 to 2024
    query_prices = """
        SELECT p.ticker,
               SUM(CASE WHEN YEAR(p.date) = 2013 THEN 1 ELSE 0 END) AS prices_2013,
               SUM(CASE WHEN YEAR(p.date) = 2014 THEN 1 ELSE 0 END) AS prices_2014,
               SUM(CASE WHEN YEAR(p.date) = 2015 THEN 1 ELSE 0 END) AS prices_2015,
               SUM(CASE WHEN YEAR(p.date) = 2016 THEN 1 ELSE 0 END) AS prices_2016,
               SUM(CASE WHEN YEAR(p.date) = 2017 THEN 1 ELSE 0 END) AS prices_2017,
               SUM(CASE WHEN YEAR(p.date) = 2018 THEN 1 ELSE 0 END) AS prices_2018,
               SUM(CASE WHEN YEAR(p.date) = 2019 THEN 1 ELSE 0 END) AS prices_2019,
               SUM(CASE WHEN YEAR(p.date) = 2020 THEN 1 ELSE 0 END) AS prices_2020,
               SUM(CASE WHEN YEAR(p.date) = 2021 THEN 1 ELSE 0 END) AS prices_2021,
               SUM(CASE WHEN YEAR(p.date) = 2022 THEN 1 ELSE 0 END) AS prices_2022,
               SUM(CASE WHEN YEAR(p.date) = 2023 THEN 1 ELSE 0 END) AS prices_2023,
               SUM(CASE WHEN YEAR(p.date) = 2024 THEN 1 ELSE 0 END) AS prices_2024
        FROM prices p
        GROUP BY p.ticker
    """
    cursor.execute(query_prices)
    prices_data = cursor.fetchall()

    # Combine ratings and prices data into a single list
    data_overview = []
    ticker_set = set([row['ticker'] for row in ratings_data] + [row['ticker'] for row in prices_data])

    for ticker in ticker_set:
        # Find the matching ratings and prices data for each ticker
        ratings = next((r for r in ratings_data if r['ticker'] == ticker), {})
        prices = next((p for p in prices_data if p['ticker'] == ticker), {})

        data_overview.append({
            'ticker': ticker,
            'ratings_2013': ratings.get('ratings_2013', 0),
            'ratings_2014': ratings.get('ratings_2014', 0),
            'ratings_2015': ratings.get('ratings_2015', 0),
            'ratings_2016': ratings.get('ratings_2016', 0),
            'ratings_2017': ratings.get('ratings_2017', 0),
            'ratings_2018': ratings.get('ratings_2018', 0),
            'ratings_2019': ratings.get('ratings_2019', 0),
            'ratings_2020': ratings.get('ratings_2020', 0),
            'ratings_2021': ratings.get('ratings_2021', 0),
            'ratings_2022': ratings.get('ratings_2022', 0),
            'ratings_2023': ratings.get('ratings_2023', 0),
            'ratings_2024': ratings.get('ratings_2024', 0),
            'prices_2013': prices.get('prices_2013', 0),
            'prices_2014': prices.get('prices_2014', 0),
            'prices_2015': prices.get('prices_2015', 0),
            'prices_2016': prices.get('prices_2016', 0),
            'prices_2017': prices.get('prices_2017', 0),
            'prices_2018': prices.get('prices_2018', 0),
            'prices_2019': prices.get('prices_2019', 0),
            'prices_2020': prices.get('prices_2020', 0),
            'prices_2021': prices.get('prices_2021', 0),
            'prices_2022': prices.get('prices_2022', 0),
            'prices_2023': prices.get('prices_2023', 0),
            'prices_2024': prices.get('prices_2024', 0)
        })

    cursor.close()
    conn.close()

    return render_template('data.html', data_overview=data_overview)


@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


@app.route('/report/<ticker>/<report_date>')
def show_report(ticker, report_date):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Fetch stock details and report data using ticker and report_date
        cursor.execute("""
            SELECT r.*, s.stock_name AS stock_name, s.ticker_symbol 
            FROM Reports r
            JOIN StockInformation s ON r.stock_id = s.stock_id
            WHERE s.ticker_symbol = %s AND DATE(r.report_date) = %s
            """, (ticker, report_date))
        report_data = cursor.fetchone()

        if not report_data:
            return "Report not found.", 404

        # Fetch financial data
        cursor.execute("SELECT * FROM FinancialPerformance WHERE report_id = %s", (report_data['report_id'],))
        financial_data = cursor.fetchone()

        # Fetch business segments
        cursor.execute("SELECT * FROM BusinessSegments WHERE report_id = %s", (report_data['report_id'],))
        business_segments = cursor.fetchall()

        # Fetch valuation metrics (including valuation_method)
        cursor.execute("SELECT * FROM ValuationMetrics WHERE report_id = %s", (report_data['report_id'],))
        valuation_metrics = cursor.fetchone()

        # Fetch risk factors
        cursor.execute("SELECT risk FROM RiskFactors WHERE report_id = %s", (report_data['report_id'],))
        risk_factors = [row['risk'] for row in cursor.fetchall()]

    finally:
        cursor.close()
        conn.close()

    # Render the report page with the fetched data
    return render_template(
        'report.html', 
        ticker=ticker,
        report_date=report_date,
        stock_name=report_data['stock_name'],
        stock_logo="https://logo-url.com/" + ticker + ".png",
        report_data=report_data,
        financial_data=financial_data,
        business_segments=business_segments,
        valuation_metrics=valuation_metrics,
        risk_factors=risk_factors
    )


# Custom filter to format large numbers and remove decimals
@app.template_filter('format_number')
def format_number(value):
    if isinstance(value, (int, float)):
        return f"{int(value):,}"  # Remove decimals and format with commas
    return value



@app.route('/join_club', methods=['POST'])
def join_club():
    email = request.form['email']
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

    try:
        # Check if the email is already in the database
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        existing_user = cursor.fetchone()

        if existing_user:
            # Email is already registered, redirect to login page
            return redirect(url_for('login', message="You are already a member", email=email))

        # Insert new email into the database
        cursor.execute("INSERT INTO users (email) VALUES (%s)", (email,))
        conn.commit()

        # Successful registration, redirect to the sign-up page
        return redirect(url_for('membership_step1', email=email))

    except mysql.connector.Error as err:
        # Rollback in case of an error
        conn.rollback()
        return render_template('membership_pro.html', message="An error occurred. Please try again later.", email=email)

    finally:
        cursor.close()
        conn.close()


@app.route('/sitemap.xml', methods=['GET'])
def sitemap():
    """Generate sitemap.xml."""
    pages = []
    ten_days_ago = (datetime.now() - timedelta(days=10)).date().isoformat()

    # Static URLs
    static_urls = [
        {'url': url_for('index', _external=True), 'lastmod': ten_days_ago, 'changefreq': 'daily', 'priority': '1.0'},
        {'url': url_for('portfolio', _external=True), 'lastmod': ten_days_ago, 'changefreq': 'weekly', 'priority': '0.8'},
        {'url': url_for('performance', _external=True), 'lastmod': ten_days_ago, 'changefreq': 'weekly', 'priority': '0.8'},
        {'url': url_for('weekly_updates', _external=True), 'lastmod': ten_days_ago, 'changefreq': 'weekly', 'priority': '0.8'},
        {'url': url_for('coverage', _external=True), 'lastmod': ten_days_ago, 'changefreq': 'weekly', 'priority': '0.8'},
        # Add more static pages as necessary
    ]

    # Add static URLs to pages
    for url in static_urls:
        pages.append(url)

    # Connect to database
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

    # Fetch dynamic stock ticker pages
    cursor.execute("SELECT ticker FROM stock")
    tickers = cursor.fetchall()

    for ticker in tickers:
        pages.append({
            'url': url_for('stock_detail', ticker=ticker['ticker'], _external=True),
            'lastmod': ten_days_ago,  # Add last modified date dynamically if available
            'changefreq': 'monthly',
            'priority': '0.6'
        })

    # Fetch dynamic question/answer pages for each ticker
    cursor.execute("SELECT id FROM InvestmentReports")
    questions = cursor.fetchall()

    for question in questions:
        pages.append({
            'url': url_for('view_answer', question_id=question['id'], _external=True),
            'lastmod': ten_days_ago,
            'changefreq': 'monthly',
            'priority': '0.5'
        })

    cursor.close()
    conn.close()

    # Generate the XML sitemap
    sitemap_xml = render_template('sitemap_template.xml', pages=pages)
    response = make_response(sitemap_xml)
    response.headers["Content-Type"] = "application/xml"

    return response

@app.route('/monthly-variations')
def monthly_variations():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Fetch S&P 500 and portfolio values at the last day of each month since Oct 1st, 2014
    query = """
    SELECT DATE_FORMAT(date, '%Y-%m') AS month,
           MAX(CASE WHEN ticker = 'SPX' THEN close END) AS sp500_close,
           MAX(CASE WHEN ticker = 'PORTFOLIO' THEN close END) AS portfolio_close
    FROM portfolio365
    WHERE date >= '2014-10-01'
    GROUP BY DATE_FORMAT(date, '%Y-%m')
    ORDER BY DATE_FORMAT(date, '%Y-%m')
    """
    cursor.execute(query)
    data = cursor.fetchall()
    cursor.close()
    conn.close()

    # Calculate variations
    for i in range(1, len(data)):
        sp500_prev = data[i-1]['sp500_close']
        portfolio_prev = data[i-1]['portfolio_close']
        
        sp500_curr = data[i]['sp500_close']
        portfolio_curr = data[i]['portfolio_close']
        
        # Calculate monthly variations
        data[i]['sp500_variation'] = ((sp500_curr - sp500_prev) / sp500_prev) * 100 if sp500_prev else None
        data[i]['portfolio_variation'] = ((portfolio_curr - portfolio_prev) / portfolio_prev) * 100 if portfolio_prev else None
        
        # Calculate delta
        data[i]['delta'] = data[i]['portfolio_variation'] - data[i]['sp500_variation'] if data[i]['portfolio_variation'] is not None and data[i]['sp500_variation'] is not None else None

    return render_template('monthly_variations.html', data=data)


@app.route('/performance')
def performance():
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

    # Fetch portfolio and S&P 500 data from `portfolio365` for performance page
    cursor.execute("""
        SELECT p.date, p.total_value AS total_portfolio_value, 
               (SELECT close 
                FROM prices sp 
                WHERE sp.ticker = 'SPX' AND sp.date <= p.date 
                ORDER BY sp.date DESC LIMIT 1) AS sp500_value
        FROM portfolio365 p
        ORDER BY p.date
    """)
    portfolio_data = cursor.fetchall()

    cursor.close()
    conn.close()

    # Extract data for charts
    dates_simulation = [row['date'].strftime('%Y-%m-%d') for row in portfolio_data]
    simulation_values = [row['total_portfolio_value'] for row in portfolio_data]
    sp500_values_simulation = [row['sp500_value'] for row in portfolio_data]

    # Reuse annualized returns calculation
    def fetch_annualized_data(period_days):
        end_date = datetime.strptime(dates_simulation[-1], '%Y-%m-%d')
        start_date = end_date - timedelta(days=period_days)
        filtered_dates, filtered_portfolio, filtered_sp500 = [], [], []
        for date, portfolio, sp500 in zip(dates_simulation, simulation_values, sp500_values_simulation):
            date_obj = datetime.strptime(date, '%Y-%m-%d')
            if date_obj >= start_date:
                filtered_dates.append(date)
                filtered_portfolio.append(portfolio)
                filtered_sp500.append(sp500)
        if len(filtered_portfolio) > 1:
            portfolio_return = calculate_annualized_return(filtered_portfolio[0], filtered_portfolio[-1], start_date, end_date)
            sp500_return = calculate_annualized_return(filtered_sp500[0], filtered_sp500[-1], start_date, end_date)
            return round(portfolio_return * 100, 1), round(sp500_return * 100, 1)
        return 0, 0

    annualized_returns = {
        "10years": fetch_annualized_data(365 * 10),
        "3years": fetch_annualized_data(365 * 3),
        "12months": fetch_annualized_data(365),
    }

    return render_template(
        'performance.html',
        dates_simulation=dates_simulation,
        simulation_values=simulation_values,
        sp500_values_simulation=sp500_values_simulation,
        annualized_returns=annualized_returns
    )


@app.route("/create_account", methods=["POST"])
def api_create_account():
    data = request.json  # Expect JSON data from the frontend
    try:
        response = create_account(data)  # Pass data to the function
        return jsonify(response), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route('/alpaca', methods=['GET'])
@login_required
def alpaca_account():
    return render_template('alpaca.html')



if __name__ == '__main__':
    app.debug = True
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
