from flask import Flask, render_template
import mysql.connector
from datetime import datetime

app = Flask(__name__)

# Database connection configuration
db_config = {
    'user': 'doadmin',
    'password': 'your_mysql_password',
    'host': 'db-mysql-nyc3-03005-do-user-4526552-0.h.db.ondigitalocean.com',
    'database': 'defaultdb',
    'port': 25060
}

def get_top_stocks():
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

    # Get today's date
    current_date = datetime.now().date()

    # Query to get the top 10 stocks from the portfolio table
    query = """
        SELECT p.ticker, a.last_closing_price AS last_price, a.expected_return
        FROM portfolio p
        JOIN analysis a ON p.ticker = a.ticker
        WHERE p.date = %s
        ORDER BY p.ranking
        LIMIT 10
    """
    cursor.execute(query, (current_date,))
    top_stocks = cursor.fetchall()

    cursor.close()
    conn.close()
    return top_stocks

@app.route('/')
def index():
    top_stocks = get_top_stocks()
    return render_template('index.html', stocks=top_stocks)

# Run the Flask app
app.run(debug=True)
