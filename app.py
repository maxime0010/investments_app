from flask import Flask, render_template
import mysql.connector
from datetime import datetime
import os

app = Flask(__name__)

# Database connection configuration
db_config = {
    'user': 'doadmin',
    'password': os.getenv('MYSQL_MDP'),
    'host': 'db-mysql-nyc3-03005-do-user-4526552-0.h.db.ondigitalocean.com',
    'database': 'defaultdb',
    'port': 25060
}

def get_latest_portfolio_date():
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(date) FROM portfolio")
    latest_date = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return latest_date

def get_top_stocks(latest_date):
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

    query = """
        SELECT p.ticker, a.last_closing_price AS last_price, a.expected_return
        FROM portfolio p
        JOIN analysis a ON p.ticker = a.ticker
        WHERE p.date = %s
        ORDER BY p.ranking
        LIMIT 10
    """
    cursor.execute(query, (latest_date,))
    top_stocks = cursor.fetchall()

    cursor.close()
    conn.close()
    return top_stocks

@app.route('/')
def index():
    latest_date = get_latest_portfolio_date()
    top_stocks = get_top_stocks(latest_date)
    return render_template('index.html', stocks=top_stocks)

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

    dates = [entry['date'].strftime('%Y-%m-%d') for entry in performance_data]
    values = [entry['total_portfolio_value'] for entry in performance_data]

    # Calculate returns
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

if __name__ == '__main__':
    app.debug = True
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
