from flask import Flask, render_template, session, redirect
from flask.globals import request
from flask.helpers import url_for
from markupsafe import escape
from flask_bcrypt import Bcrypt
from flask_mysqldb import MySQL
import os

app = Flask(__name__)
mysql = MySQL(app)
bcrypt = Bcrypt(app)

# configuring app
app.debug = os.getenv("DEBUG")
app.env = os.getenv("FLASK_ENV")
app.secret_key = os.getenv('SECRET_KEY')

# configuring mysql db connection
app.config['MYSQL_HOST'] = os.getenv("MYSQL_HOST")
app.config['MYSQL_USER'] = os.getenv("MYSQL_USER")
app.config['MYSQL_PASSWORD'] = os.getenv("MYSQL_PASSWORD")
app.config['MYSQL_DB'] = os.getenv("MYSQL_DB")
app.config['MYSQL_PORT'] = int(os.getenv("MYSQL_PORT"))

@app.route('/')
def index():
    if 'username' in session:
        return render_template('menu.html', name=session['username'])
    else:
        return render_template('index.html')

# return a list of tuples of users' user and password
def fetch_users():
    cur = mysql.connection.cursor()
    cur.execute('''
        SELECT uname AS username, pword AS password FROM music.users
    ''')
    rv = cur.fetchall()
    return list(rv)

@app.route('/login', methods=['POST'])
def login():
    users = fetch_users()
    data = request.form
    username_candidate, password_candidate = data.get('username'), data.get('password')
    for (username, password) in users:
        if (username == username_candidate and bcrypt.check_password_hash(password, password_candidate)): # matches
            session['username'] = username
            return redirect(url_for('index'))
    return render_template('index.html', error="Invalid credentials!")
    
