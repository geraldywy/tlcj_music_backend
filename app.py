import enum
from flask import Flask, render_template, session, redirect, jsonify
from flask.globals import request
from flask.helpers import url_for
from markupsafe import escape
from flask_bcrypt import Bcrypt
from flask_mysqldb import MySQL
from flask_cors import CORS, cross_origin
import os
import io
from base64 import encodebytes
import shutil
from PIL import Image

from werkzeug.utils import secure_filename

app = Flask(__name__)
mysql = MySQL(app)
bcrypt = Bcrypt(app)
cors = CORS(app)

# configuring app
app.debug = os.getenv("DEBUG")
app.env = os.getenv("FLASK_ENV")
app.secret_key = os.getenv('SECRET_KEY')
app.config['CORS_HEADERS'] = 'Content-Type'

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
        SELECT uname AS username, pword AS password FROM music.users;
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
        SELECT * FROM music.songs;
    ''')
    rv = cur.fetchall()
    global originals
    global covers
    global pinned
    originals = []
    covers = []
    pinned = []
    for song in rv:
        title, link, category, pin, source = song
        if pin:
            pinned.append(song)
        if category.lower() == "originals":
            originals.append(song)
        elif category.lower() == "covers":
            covers.append(song)
    
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
                UPDATE music.songs SET pinned=false WHERE title='{unpin_title}' AND link='{unpin_link}';
            ''')
        cur.execute(f'''
            INSERT INTO music.songs VALUES ('{title}', '{link}', '{cat}', {1 if to_pin else 0}, '{source}');
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
        # clean to_pin into a boolean
        if isinstance(to_pin, str):
            if (to_pin.lower() == "true"):
                to_pin = True
            else:
                to_pin = False
        if to_pin and (not unpinned):
            return render_template("add_song.html", pinned=pinned, feedback="Error: Selected pin option, but did not choose a song to unpin")
        
        if title and link and source and cat: # all options selected
            if insert_song(title, link, source, cat, to_pin, unpinned):
                return render_template("add_song.html", pinned=pinned, feedback="Successfully added " + title)
            else:
                return render_template("add_song.html", pinned=pinned, feedback="Error adding " + title + ". Form was filled correctly. Error uploading to the MYSQL DB.")
        else:
            return render_template("add_song.html", pinned=pinned, feedback="Error: Incomplete form")

# changing of pins is not done here, however, changes made to a song that is pinned must be reflected also in the pinned list
@app.route("/edit_song_info", methods=["POST"])
def edit_song_info():
    if not valid():
        return "ERROR: NOT AUTHENTICATED"

    title, link = request.form.get("song_title"), request.form.get("song_link")

    if not (title or link):
        return redirect(url_for("modify_music"))

    # match song_title and link in the originals/pinned list and fetch its data
    song_to_edit = None
    for song in originals:
        s_title, s_link, _, _, _ = song
        info = s_title, s_link
        if info == (title, link):
            song_to_edit = song
            break
    if not song_to_edit: # song exists in covers
        for song in covers:
            s_title, s_link, _, _, _ = song
            info = s_title, s_link
            if info == (title, link):
                song_to_edit = song
                break
    return render_template("edit_song_info.html", song=song_to_edit)

def update_song_db(old_title, old_link, title, link, cat, to_pin, source):
    cur = mysql.connection.cursor()
    try:
        cur.execute(f'''
            UPDATE music.songs SET title = '{title}', link = '{link}', 
            category = '{cat}', pinned = {1 if to_pin else 0}, source = '{source}'
            WHERE title = '{old_title}' and link = '{old_link}';
        ''')
        mysql.connection.commit()
        return True
    except Exception as e:
        print("Problem updating changes into db: " + str(e))
        return False

@app.route("/update_song", methods=["POST"])
def update_song():
    if not valid():
        return "ERROR: NOT AUTHENTICATED"

    old_title, old_link, title, link, source, cat, to_pin = request.form.get("old_song_title"), request.form.get("old_song_link"), \
            request.form.get("song_title"), request.form.get("song_link"), \
            request.form.get("type"), request.form.get("category"), request.form.get("pinned")

    if not (old_title and old_link and title and link and source and cat):
        return redirect(url_for('modify_music'))
    
    # sanitize to_pin
    if isinstance(to_pin, str):
        if to_pin.lower() == "true":
            to_pin = True
        else:
            to_pin = False

    new_song = title, link, cat, to_pin, source
    song_idx = -1

    # update in db
    if not update_song_db(old_title, old_link, title, link, cat, to_pin, source):
        return render_template("edit_song_info.html", song=new_song, feedback="Failed to save in the DB")
    
    # update locally, check if nid to move list
    for idx, song in enumerate(originals):
        if old_title == song[0] and old_link == song[1]:
            song_idx = idx
            break
    if song_idx != -1:
        # found the old song in originals
        if cat == "originals": # no need to move lists, no change in category
            originals[song_idx] = new_song
        else:
            originals.pop(song_idx) # delete from originals and add new song into covers
            covers.append(new_song)

    if song_idx == -1: # not found, perform the same thing for covers
        for idx, song in enumerate(covers):
            if old_title == song[0] and old_link == song[1]:
                song_idx = idx
                break

        if song_idx != -1:
            # found the old song in covers
            if cat == "covers": # no need to move lists, no change in category
                covers[song_idx] = new_song
            else:
                covers.pop(song_idx) # delete from covers and add new song into originals
                originals.append(new_song)
        else: # not found in originals or covers, invalid
            return "ERROR: SONG NOT FOUND"
    
    if to_pin:
        # this song is being pinned, nid to update it in the pinned list as well
        for idx, song in enumerate(pinned):
            if old_title == song[0] and old_link == song[1]:
                song_idx = idx
                break
        pinned[song_idx] = new_song

    return render_template("edit_song_info.html", song=new_song, feedback="updated successfully")

@app.route("/replace_pin", methods=["POST"])
def change_pins():
    if not valid():
        return "ERROR: NOT AUTHENTICATED"

    title, link = request.form.get("song_title"), request.form.get("song_link")
    if not title or not link:
        redirect(url_for('modify_music'))

    if not originals or not covers or not pinned:
        fetch_music()
    unpinned_songs = [song for song in originals+covers if not song[3]] # feed in songs to choose from
    return render_template("replace_pins.html", song=(title, link), unpinned_songs=unpinned_songs)

@app.route("/modify_pins", methods=["POST"])
def modify_pins():
    if not valid():
        return "ERROR: NOT AUTHENTICATED"

    old_pin_title, old_pin_link, new_pin_title, new_pin_link = request.form.get("old_pin_title"), request.form.get("old_pin_link"), \
            *request.form.get("pin").split(" | ")

    if not (old_pin_title and old_pin_link and new_pin_title and new_pin_link):
        return redirect(url_for('modify_music'))
    
    if not pinned:
        fetch_music()
    old_pin_song = None
    new_pin_song = None
    replace_idx = -1
    for idx, song in enumerate(pinned):
        if song[0] == old_pin_title and song[1] == old_pin_link:
            old_pin_song = song
            replace_idx = idx
            break
    for song in covers+originals:
        if song[0] == new_pin_title and song[1] == new_pin_link:
            new_pin_song = song
            break
    
    if not (old_pin_song and new_pin_song): # user likely refreshed
        return redirect(url_for("modify_music"))

    # swap pin status
    old_pin_song = (*old_pin_song[0:3], new_pin_song[3], old_pin_song[4])
    new_pin_song = (*new_pin_song[0:3], not new_pin_song[3], new_pin_song[4])

    # replace local copy
    pinned[replace_idx] = new_pin_song
    
    # replace in db
    update_song_db(old_pin_song[0], old_pin_song[1], *old_pin_song)
    update_song_db(new_pin_song[0], new_pin_song[1], *new_pin_song)

    return render_template("modify_music.html", pinned=pinned, originals=originals, covers=covers, feedback="Pinned songs updated!")
    
def delete_song_db(title, link):
    cur = mysql.connection.cursor()
    try:
        cur.execute(f'''
            DELETE FROM music.songs WHERE title = '{title}' and link = '{link}';
        ''')
        mysql.connection.commit()
        return True
    except Exception as e:
        print("Problem deleting song in db: " + str(e))
        return False

@app.route("/delete_song", methods=["POST"])
def delete_song():
    if not valid():
        return "ERROR: NOT AUTHENTICATED"
    
    if not pinned:
        fetch_music()
    
    title, link = request.form.get("song_title"), request.form.get("song_link")
    
    idx = -1
    for i, song in enumerate(covers + originals):
        if song[0] == title and song[1] == link: # found song
            idx = i
            break

    # check again if it is in pinned
    for song in pinned:
        if (song[0] == title and song[1] == link) or idx == -1: # check if song is even in covers or originals 
            return redirect(url_for("modify_music")) # redirect since user might refresh also
    
    # delete local copy
    if idx < len(covers): # song belongs to covers
        covers.pop(idx)
    else:
        originals.pop(idx - len(covers))

    # delete in DB
    if delete_song_db(title, link):
        return render_template("modify_music.html", pinned=pinned, originals=originals, covers=covers, feedback="successfully deleted " + title)
    else:
        return render_template("modify_music.html", pinned=pinned, originals=originals, covers=covers, feedback="failed to delete in DB: " + title)

# api endpoint to display music lists
@app.route("/v1/api/music")
@cross_origin()
def display_music():
    originals, covers, pinned = fetch_music()
    return jsonify({
        "pinned": pinned,
        "originals": originals,
        "covers": covers
    })
