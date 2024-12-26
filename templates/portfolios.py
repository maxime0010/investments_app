{% extends "base.html" %}

{% block title %}Portfolio Hypotheses - Good Life{% endblock %}

{% block content %}
<div class="container">
    <h1>Portfolio Hypotheses Management</h1>
    
    <!-- Create New Portfolio Form -->
    <form id="createPortfolioForm" method="POST" action="{{ url_for('create_portfolio') }}">
        <h2>Create New Portfolio</h2>
        <div class="form-group">
            <label for="newPortfolioName">Portfolio Name:</label>
            <input type="text" id="newPortfolioName" name="portfolio_name" class="form-control" required>
        </div>
        <button type="submit" class="btn btn-primary">Create Portfolio</button>
    </form>

    <hr>

    <!-- Add Hypothesis Form -->
    <form id="addHypothesisForm" method="POST" action="{{ url_for('add_hypothesis') }}">
        <h2>Add New Hypothesis</h2>
        <div class="form-group">
            <label for="portfolioId">Portfolio ID:</label>
            <input type="number" id="portfolioId" name="portfolio_id" class="form-control" required>
        </div>
        <div class="form-group">
            <label for="variable">Variable:</label>
            <input type="text" id="variable" name="variable" class="form-control" required>
        </div>
        <div class="form-group">
            <label for="value">Value:</label>
            <input type="text" id="value" name="value" class="form-control" required>
        </div>
        <button type="submit" class="btn btn-primary">Add Hypothesis</button>
    </form>

    <hr>

    <!-- Update Existing Portfolio Form -->
    <form id="updatePortfolioForm" method="POST" action="{{ url_for('update_portfolio') }}">
        <h2>Update Portfolio</h2>
        <div class="form-group">
            <label for="updatePortfolioId">Portfolio ID:</label>
            <input type="number" id="updatePortfolioId" name="portfolio_id" class="form-control" required>
        </div>
        <div class="form-group">
            <label for="updateVariable">Variable:</label>
            <input type="text" id="updateVariable" name="variable" class="form-control" required>
        </div>
        <div class="form-group">
            <label for="updateValue">Value:</label>
            <input type="text" id="updateValue" name="value" class="form-control" required>
        </div>
        <button type="submit" class="btn btn-primary">Update Portfolio</button>
    </form>
</div>
{% endblock %}
