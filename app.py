from flask import Flask, render_template, session, redirect, jsonify
from flask.globals import request
from flask.helpers import url_for
from markupsafe import escape
from flask_bcrypt import Bcrypt
from flask_mysqldb import MySQL
import os
import io
from base64 import encodebytes
import shutil
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
pinned = []
originals = []
covers = []

@app.after_request
def add_header(response):
    """
    Add headers to both force latest IE rendering engine or Chrome Frame,
    and also to cache the rendered page for 10 minutes.
    """
    response.headers['X-UA-Compatible'] = 'IE=Edge,chrome=1'
    response.headers['Cache-Control'] = 'public, max-age=0'
    response.cache_control.no_store = True
    return response

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
    # clean up files that are not sig-logo.jpg or pic[1-8].jpg
    allowed_pics = [f'pic{i}' for i in range(1, 9)]
    allowed_pics.append("sig-logo")
    pics = []
    for filename in os.listdir("." + app.static_url_path + "/images/"):
        if filename.split(".")[0] not in allowed_pics:
            os.remove("." + format_home_pic_path(filename))
        else:
            pics.append(format_home_pic_path(filename))
    return pics

@app.route("/home")
def modify_home():
    if not valid():
        return "ERROR: Not Authenticated"
    pics = get_home_pics()
    return render_template("modify_home.html", pics=pics)

ALLOWED_EXTENSIONS = {'jpg', 'jpeg'}
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
        pics[num] = format_home_pic_path(filename)
        os.remove("." + old_filename)
        new_pic.save("." + format_home_pic_path(filename))
        shutil.copy("." + format_home_pic_path(filename), "." + old_filename)
        return render_template("modify_home.html", pics=pics, feedback="Updated!")
    else:
        return render_template("modify_home.html", pics=pics, error="Image file must be .jpg")

# query db for a list of music, tagged as original/cover/pinned
# data columns: [ title | link | category | pinned ]
def fetch_music():
    cur = mysql.connection.cursor()
    cur.execute('''
        SELECT * FROM music.songs
    ''')
    rv = cur.fetchall()
    global originals
    global covers
    global pinned
    originals = []
    covers = []
    pinned = []
    for song in rv:
        title, link, category, pin = song
        info = (title, link)
        if pin:
            pinned.append(info)
        if category.lower() == "originals":
            originals.append(info)
        elif category.lower() == "covers":
            covers.append(info)
    
    return originals, covers, pinned

@app.route("/music", methods=["GET"])
def modify_music():
    if not valid():
        return "ERROR: NOT AUTHENTICATED"
    originals, covers, pinned = fetch_music()
    return render_template("modify_music.html", pinned=pinned, originals=originals, covers=covers)

def insert_song(title, link, source, cat, to_pin, unpinned):
    cur = mysql.connection.cursor()
    try:
        if unpinned:
            unpin_title, unpin_link = unpinned.split(" | ")
            # unpin the song to unpin first
            cur.execute(f'''
                UPDATE music.songs SET pinned=false WHERE title='{unpin_title}' AND link='{unpin_link}'
            ''')
        cur.execute(f'''
            INSERT INTO music.songs VALUES ('{title}', '{link}', '{cat}', {"true" if to_pin else "false"})
        ''')
        mysql.connection.commit()
        return True
    except Exception as e:
        print("Problem inserting into db: " + str(e))
        return False

@app.route("/add_song", methods=["GET", "POST"])
def add_song():
    if not valid():
        return "ERROR: NOT AUTHENTICATED"
    if not pinned: # if pinned is empty, uninitialized
        fetch_music() # populate the states, we do not need to use the return value, since it is global

    if request.method == "GET":
        return render_template("add_song.html", pinned=pinned)
    else:
        title, link, source, cat, to_pin, unpinned = request.form.get("song_title"), request.form.get("song_link"), \
            request.form.get("type"), request.form.get("category"), request.form.get("pinned"), request.form.get("unpin")
        # sanity check, if we choose to pin, there must be something to unpin
        # maintain constant 3 pins
        if to_pin == "yes" and not unpinned:
            return render_template("add_song.html", pinned=pinned, feedback="Error: Selected pin option, but did not choose a song to unpin")
        print(title, link, source, cat, to_pin, unpinned)
        if title and link and source and cat and to_pin: # all options selected
            if insert_song(title, link, source, cat, to_pin, unpinned):
                return render_template("add_song.html", pinned=pinned, feedback="Successfully added " + title)
            else:
                return render_template("add_song.html", pinned=pinned, feedback="Error adding " + title + ". Form was filled correctly. Error uploading to the MYSQL DB.")
        else:
            return render_template("add_song.html", pinned=pinned, feedback="Error: Incomplete form")

