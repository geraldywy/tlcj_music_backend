from flask import Flask, render_template, session, redirect, jsonify
from flask.globals import request
from flask.helpers import url_for
from markupsafe import escape
from flask_bcrypt import Bcrypt
from flask_mysqldb import MySQL
import os
import io
from base64 import encodebytes
from PIL import Image

from werkzeug.utils import secure_filename

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

pics = []

@app.route('/', methods=["GET"])
def index():
    if valid():
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

# helper method to check if user is logged in
def valid():
    return 'username' in session

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
    
@app.route("/logout", methods=["GET"])
def logout():
    session.pop('username', None)
    return redirect(url_for('index'))

def format_home_pic_path(filename):
    return url_for("static", filename="images/" + filename)

# home pics must be stored in static/images directory
def get_home_pics():
    return [format_home_pic_path(filename) for filename in os.listdir("./" + app.static_url_path + "/images/")]

@app.route("/home")
def modify_home():
    if not valid():
        return "ERROR: Not Authenticated"
    pics = get_home_pics()
    return render_template("modify_home.html", pics=pics)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
def allowed_file(filename):
    return '.' in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route("/replace_home_pic/<num>", methods=["GET", "POST"])
def replace_home_pic(num):
    if not valid():
        return "ERROR: NOT AUTHENTICATED"
    pics = get_home_pics()
    num = int(num) - 1
    old_filename = pics[num]
    if request.method == "GET":
        return redirect(url_for('modify_home'))
    if 'new_pic' not in request.files:
        return render_template("modify_home.html", pics=pics, error="File not in request")
    new_pic = request.files['new_pic']
    if new_pic.filename == "":
        return render_template("modify_home.html", pics=pics, error="No selected file")
    if new_pic and allowed_file(new_pic.filename):
        filename = secure_filename(new_pic.filename)
        pics[num] = filename
        os.remove("." + old_filename)
        new_pic.save("." + format_home_pic_path(filename))
        return redirect(url_for("modify_home", pics=pics))

def get_response_image(image_path):
    pil_image = Image.open(image_path, mode='r')
    byte_arr = io.BytesIO()
    pic_format = "JPG" if os.path.splitext(image_path)[1].upper() in ("JPEG", "JPG") else "PNG"
    pil_image.save(byte_arr, format=pic_format)
    encoded_img = encodebytes(byte_arr.getvalue()).decode('ascii')
    return encoded_img

# works but takes really long cause of base64 data
# need to reconsider if this is the best way to do this
@app.route("/v1/api/get_home_wallpapers", methods=["GET"])
def get_home_wallpapers():
    if not valid():
        return "ERROR: NOT AUTHENTICATED!"
    encoded_images = []
    for image_path in get_home_pics():
        encoded_images.append(get_response_image("." + image_path))
    return jsonify({'wallpapers': encoded_images})
    
