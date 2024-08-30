{% extends "base.html" %}

{% block title %}Coverage - Good Life{% endblock %}

{% block content %}
<div class="container my-5">
    <h1 class="mb-4">Coverage</h1>
    <p>Number of stocks covered: <strong>{{ num_stocks }}</strong></p> <!-- Display the number of stocks -->
    <p>Last updated on: <strong>{{ last_updated.strftime('%Y-%m-%d') }}</strong></p> <!-- Display the last updated date -->
    <table class="table table-striped">
        <thead>
            <tr>
                <th scope="col">Name</th>
                <th scope="col">Ticker</th>
                <th scope="col">Indices</th>
                <th scope="col">Last Closing Price</th>
                <th scope="col">Average Price Target</th>
                <th scope="col">Number of Analysts</th>
                <th scope="col">Updates in the last {{ recent_days }} days</th>
                <th scope="col">Top Performing Analysts</th>
                <th scope="col">Refined Price Target</th>
                <th scope="col">Expected Return</th>
            </tr>
        </thead>
        <tbody>
            {% for stock in coverage_data %}
            <tr>
                <td><a href="{{ url_for('stock_detail', ticker=stock.ticker) }}">{{ stock.stock_name }}</a></td>
                <td><a href="{{ url_for('stock_detail', ticker=stock.ticker) }}">{{ stock.ticker }}</a></td>
                <td>
                    {% for index in stock.indices.split(',') %}
                        <span class="badge badge-tag">{{ index }}</span>
                    {% endfor %}
                </td>
                <td>${{ stock.last_closing_price }}</td>
                {% if current_user.is_authenticated and current_user.is_member %}
                    <td>${{ stock.average_price_target }}</td>
                    <td>{{ stock.num_analysts }}</td>
                    <td>{{ stock.num_high_success_analysts }}</td>
                    <td>${{ stock.avg_combined_criteria }}</td>
                    <td>{{ stock.expected_return_combined_criteria }}%</td>
                {% else %}
                    <!-- Apply the overlay effect to these columns for non-members -->
                    <td colspan="4">
                        <div class="overlay-card">
                            <div class="overlay">
                                <div class="overlay-content">Join to see more</div>
                            </div>
                        </div>
                    </td>
                {% endif %}
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endblock %}

{% block styles %}
<style>
    .overlay-card {
        position: relative;
        overflow: hidden;
    }
    .overlay {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background-color: rgba(0, 0, 0, 0.5); /* 50% opacity */
        backdrop-filter: blur(8px); /* Apply blurring effect */
        -webkit-backdrop-filter: blur(8px); /* Safari support */
        filter: blur(8px); /* Fallback for other browsers */
        color: white;
        display: flex;
        justify-content: center;
        align-items: center;
        text-align: center;
        opacity: 1;
        z-index: 1;
    }
    .overlay-content {
        z-index: 2;
        font-size: 1.2rem;
        font-weight: bold;
    }
</style>
{% endblock %}
