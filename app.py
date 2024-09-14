@app.route('/performance')
def performance():
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

    # Fetch actual portfolio values from your table (replace with actual table name)
    cursor.execute("""
        SELECT date, total_portfolio_value
        FROM actual_portfolio  -- Replace with your actual portfolio table
        ORDER BY date
    """)
    actual_portfolio_data = cursor.fetchall()

    # Fetch simulated portfolio values from portfolio_simulation
    cursor.execute("""
        SELECT date, total_portfolio_value
        FROM portfolio_simulation
        ORDER BY date
    """)
    simulated_portfolio_data = cursor.fetchall()

    # Fetch S&P 500 data for both graphs
    cursor.execute("""
        SELECT date, sp500_value
        FROM sp500_data  -- Replace with your S&P 500 table
        ORDER BY date
    """)
    sp500_data = cursor.fetchall()

    cursor.close()
    conn.close()

    # Extract dates and values
    dates_actual = [row['date'].strftime('%Y-%m-%d') for row in actual_portfolio_data]
    actual_portfolio_values = [row['total_portfolio_value'] for row in actual_portfolio_data]

    dates_simulation = [row['date'].strftime('%Y-%m-%d') for row in simulated_portfolio_data]
    simulated_portfolio_values = [row['total_portfolio_value'] for row in simulated_portfolio_data]

    sp500_values_actual = [row['sp500_value'] for row in sp500_data[:len(dates_actual)]]
    sp500_values_simulation = [row['sp500_value'] for row in sp500_data[:len(dates_simulation)]]

    return render_template('performance.html', 
                           dates_actual=dates_actual, 
                           actual_values=actual_portfolio_values, 
                           sp500_values_actual=sp500_values_actual, 
                           dates_simulation=dates_simulation, 
                           simulation_values=simulated_portfolio_values, 
                           sp500_values_simulation=sp500_values_simulation)
