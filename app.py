from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, json, request, current_app
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

    # Fetch the expected return, number of analysts with success rate above median, and recent updates
    cursor.execute("""
        SELECT expected_return_combined_criteria, num_recent_analysts, num_high_success_analysts
        FROM analysis
        WHERE ticker = %s
    """, (ticker,))
    analysis_data = cursor.fetchone()

    # Fetch the latest non-zero stock price
    cursor.execute("""
        SELECT close
        FROM prices
        WHERE ticker = %s AND close > 0
        ORDER BY date DESC
        LIMIT 1
    """, (ticker,))
    latest_stock_price_result = cursor.fetchone()
    latest_stock_price = latest_stock_price_result['close'] if latest_stock_price_result else None

    # Calculate the median success rate directly in SQL
    cursor.execute("""
        WITH ordered_analysts AS (
            SELECT overall_success_rate, ROW_NUMBER() OVER (ORDER BY overall_success_rate) AS rn, COUNT(*) OVER() AS cnt
            FROM analysts
        )
        SELECT ROUND(AVG(overall_success_rate), 2) AS median_success_rate
        FROM ordered_analysts
        WHERE rn IN (FLOOR((cnt + 1) / 2), CEIL((cnt + 1) / 2));
    """)
    median_success_rate = cursor.fetchone()['median_success_rate']

    # Fetch only the latest rating for each analyst
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
        ORDER BY r.date DESC, r.analyst_name ASC  -- Order by last update descending
    """, (median_success_rate, ticker))
    analysts_data = cursor.fetchall()

    cursor.close()
    conn.close()

    # Prepare data for rendering
    for analyst in analysts_data:
        if analyst['price_target'] is not None and latest_stock_price is not None:
            analyst['expected_return'] = ((analyst['price_target'] - latest_stock_price) / latest_stock_price) * 100
        else:
            analyst['expected_return'] = None  # Handle zero or missing stock price

        # Highlight if updated in the last 30 days or if the analyst is a top performer
        analyst['updated_last_30_days'] = 'Yes' if analyst['updated_last_30_days'] else 'No'
        analyst['is_top_performer'] = 'Yes' if analyst['is_top_performer'] else 'No'
        analyst['grey_out'] = analyst['last_update'] < (datetime.today().date() - timedelta(days=30)) or analyst['overall_success_rate'] < median_success_rate

    return render_template('stock_detail.html', ticker=ticker, analysis_data=analysis_data, analysts_data=analysts_data, median_success_rate=median_success_rate)



@app.route('/performance')
def performance():
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

    # Fetch actual portfolio values and S&P 500 data
    cursor.execute("""
        SELECT p.date, SUM(p.total_value) AS total_portfolio_value, 
               (SELECT close 
                FROM prices sp 
                WHERE sp.ticker = 'SPX' AND sp.date <= p.date 
                ORDER BY sp.date DESC LIMIT 1) AS sp500_value
        FROM portfolio p
        GROUP BY p.date
        ORDER BY p.date
    """)
    actual_portfolio_data = cursor.fetchall()

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
    dates_actual = [row['date'].strftime('%Y-%m-%d') for row in actual_portfolio_data]
    actual_portfolio_values = [row['total_portfolio_value'] for row in actual_portfolio_data]
    sp500_values_actual = [row['sp500_value'] for row in actual_portfolio_data]

    dates_simulation = [row['date'].strftime('%Y-%m-%d') for row in simulated_portfolio_data]
    simulated_portfolio_values = [row['total_portfolio_value'] for row in simulated_portfolio_data]
    sp500_values_simulation = [row['sp500_value'] for row in simulated_portfolio_data]

    # Pass data to the template
    return render_template('performance.html', 
                           dates_actual=dates_actual, 
                           actual_values=actual_portfolio_values, 
                           sp500_values_actual=sp500_values_actual, 
                           dates_simulation=dates_simulation, 
                           simulation_values=simulated_portfolio_values, 
                           sp500_values_simulation=sp500_values_simulation)


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
    stripe_lookup_key = os.getenv('STRIPE_LOOKUP_KEY')
    return render_template('membership_step2.html', stripe_lookup_key=stripe_lookup_key)


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

    email=current_user.email,
    subscription_status, customer_id, error = get_subscription_status(email)

    if error:
        return render_template('profile.html', error=error)

    if not subscription_status:
        # If no subscription is found, redirect to the subscribe route
        return redirect(url_for('subscribe'))

    return render_template('profile.html', email=email, subscription_status=subscription_status, customer_id=customer_id)




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
    # Example list of updates
    updates = [
        {"date": "2024-09-01", "title": "Newsletter #1 - Week of Sept 1st"},
        {"date": "2024-09-08", "title": "Newsletter #2 - Week of Sept 8th"}
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

    # Fetch actual and simulated portfolio data
    cursor.execute("""
        SELECT p.date, SUM(p.total_value) AS total_portfolio_value, 
               (SELECT close 
                FROM prices sp 
                WHERE sp.ticker = 'SPX' AND sp.date <= p.date 
                ORDER BY sp.date DESC LIMIT 1) AS sp500_value
        FROM portfolio p
        GROUP BY p.date
        ORDER BY p.date
    """)
    actual_portfolio_data = cursor.fetchall()

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
    if simulated_portfolio_data:
        dates_simulation = [row['date'].strftime('%Y-%m-%d') for row in simulated_portfolio_data]
        simulation_values = [row['total_portfolio_value'] for row in simulated_portfolio_data]
        sp500_values_simulation = [row['sp500_value'] for row in simulated_portfolio_data]
    else:
        # Fallback in case of empty data
        dates_simulation = []
        simulation_values = []
        sp500_values_simulation = []

    # Get statistics
    num_reports, num_analysts, num_banks = get_ratings_statistics()

    return render_template(
        'index.html',
        num_reports=num_reports,
        num_analysts=num_analysts,
        num_banks=num_banks,
        dates_simulation=dates_simulation,
        simulation_values=simulation_values,
        sp500_values_simulation=sp500_values_simulation
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

    return render_template('coverage.html', coverage_data=filtered_coverage_data, num_stocks=num_stocks, last_updated=last_updated, recent_days='30', is_member=is_member)

@app.route('/stock_simulation/<ticker>')
def stock_simulation(ticker):
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

    # Fetch the unique tickers for the dropdown
    cursor.execute("SELECT DISTINCT ticker FROM analysis_simulation ORDER BY ticker")
    tickers = [row['ticker'] for row in cursor.fetchall()]

    # Fetch stock prices and price targets from the analysis_simulation table
    cursor.execute("""
        SELECT date, last_closing_price, avg_combined_criteria
        FROM analysis_simulation
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

    # Fetch the number of analyst ratings for each year from 2021 to 2024
    query_ratings = """
        SELECT r.ticker,
               SUM(CASE WHEN YEAR(r.date) = 2021 THEN 1 ELSE 0 END) AS ratings_2021,
               SUM(CASE WHEN YEAR(r.date) = 2022 THEN 1 ELSE 0 END) AS ratings_2022,
               SUM(CASE WHEN YEAR(r.date) = 2023 THEN 1 ELSE 0 END) AS ratings_2023,
               SUM(CASE WHEN YEAR(r.date) = 2024 THEN 1 ELSE 0 END) AS ratings_2024
        FROM ratings r
        GROUP BY r.ticker
    """
    cursor.execute(query_ratings)
    ratings_data = cursor.fetchall()

    # Fetch the number of stock prices for each year from 2021 to 2024
    query_prices = """
        SELECT p.ticker,
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
            'ratings_2021': ratings.get('ratings_2021', 0),
            'ratings_2022': ratings.get('ratings_2022', 0),
            'ratings_2023': ratings.get('ratings_2023', 0),
            'ratings_2024': ratings.get('ratings_2024', 0),
            'prices_2021': prices.get('prices_2021', 0),
            'prices_2022': prices.get('prices_2022', 0),
            'prices_2023': prices.get('prices_2023', 0),
            'prices_2024': prices.get('prices_2024', 0)
        })

    cursor.close()
    conn.close()

    return render_template('data.html', data_overview=data_overview)



if __name__ == '__main__':
    app.debug = True
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
