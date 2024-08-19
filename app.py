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

def get_top_stocks(latest_date):
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

    query = """
        SELECT p.ticker, a.last_closing_price AS last_price, a.expected_return_combined_criteria AS expected_return,
               a.num_combined_criteria AS num_analysts
        FROM portfolio p
        JOIN analysis a ON p.ticker = a.ticker
        WHERE p.date = %s
        GROUP BY p.ticker, a.last_closing_price, a.expected_return_combined_criteria, a.num_combined_criteria
        ORDER BY expected_return_combined_criteria DESC
        LIMIT 10
    """
    cursor.execute(query, (latest_date,))
    top_stocks = cursor.fetchall()

    cursor.close()
    conn.close()
    return top_stocks

@app.route('/')
def portfolio():
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()

    # Fetch the latest date from the portfolio table
    cursor.execute("SELECT MAX(date) FROM portfolio")
    latest_date = cursor.fetchone()[0]

    top_stocks = get_top_stocks(latest_date)

    formatted_date = latest_date.strftime('%Y-%m-%d') if latest_date else None
    return render_template('portfolio.html', stocks=top_stocks, last_updated=formatted_date)

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
    try:
        cursor.execute(query)
        performance_data = cursor.fetchall()
    except Exception as e:
        return f"An error occurred: {e}"

    cursor.close()
    conn.close()
    return render_template('performance.html', performance=performance_data)

if __name__ == '__main__':
    app.debug = True
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
