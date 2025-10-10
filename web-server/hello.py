from flask import request
from flask import Flask
from markupsafe import escape

app = Flask(__name__)

@app.get("/")
def hello_world():
    return "<p>Hello, World!</p>"


@app.route('/create_namespace/<username>')
def show_user_profile(username):
    # show the user profile for that user
    return {
        "username": username,
        "theme": "teste",
    }
    # return f"<p>User {escape(username)}<p>"

# @app.post("/namespace")
# def namespace():
#     user = get_current_user()
#     return {
#         "username": user.username,
#         "theme": user.theme,
#         "image": url_for("user_image", filename=user.image),
#     }

# @app.route("/users")
# def users_api():
#     users = get_all_users()
#     return [user.to_json() for user in users]