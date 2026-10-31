import json
import os
import time

import requests

from flask import (
    Flask,
    jsonify,
    render_template_string,
    request,
    session as flask_session,
    redirect,
    url_for,
)

app = Flask(__name__)

STEAM_API_KEY = os.getenv("STEAM_API_KEY", "680FC1DCD64DFE97B28BD1E17E8A75CD")
DB_FILE = "ratings.json"
SESSIONS_FILE = "sessions.json"

app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

STEAM_LOGIN_URL = "https://steamcommunity.com/openid/login"


def load_ratings():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_ratings(ratings):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(ratings, f, ensure_ascii=False, indent=4)


def load_sessions():
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_sessions(sessions):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(sessions, f, ensure_ascii=False, indent=4)


def fetch_steam_games(steam_id):
    url = (
        "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"
        f"?key={STEAM_API_KEY}&steamid={steam_id}&"
        "include_appinfo=1&include_played_free_games=1&format=json"
    )

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.Timeout:
        return {"error": "Connection timed out while requesting Steam API."}
    except requests.exceptions.HTTPError as e:
        return {"error": f"HTTP error while requesting Steam API: {e}"}
    except requests.exceptions.RequestException as e:
        return {"error": f"Steam API request failed: {e}"}
    except ValueError:
        return {"error": "Steam API returned invalid JSON."}

    games_list = data.get("response", {}).get("games", [])

    if not games_list:
        return []

    ratings = load_ratings()
    formatted_games = []

    for game in games_list:
        appid = str(game.get("appid", ""))

        if not appid:
            continue

        image_url = f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/header.jpg"

        playtime_minutes = game.get("playtime_forever")
        try:
            playtime_hours = round(int(playtime_minutes) / 60)
        except (TypeError, ValueError):
            playtime_hours = 0

        formatted_games.append(
            {
                "id": appid,
                "name": game.get("name", "Unknown game"),
                "playtime": playtime_hours,
                "image": image_url,
                "rating": ratings.get(appid, ""),
            }
        )

    formatted_games.sort(key=lambda x: x["playtime"], reverse=True)
    return formatted_games


@app.route("/")
def index():
    logged_in_steam_id = flask_session.get("steam_id")

    html_template = """
    <!DOCTYPE html>
    <html lang="uk">
    <head>
        <meta charset="UTF-8">
        <title>Мій Ігровий Трекер</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                background: #1b2838;
                color: #c7d5e0;
                padding: 20px;
            }
            h1 {
                color: #66c0f4;
            }
            .auth-box {
                display: grid;
                gap: 10px;
                margin-bottom: 20px;
            }
            input {
                padding: 10px;
                font-size: 16px;
                border: none;
                border-radius: 4px;
            }
            input {
                width: 300px;
                background: #2a475e;
                color: #fff;
            }
            button {
                background: #5c7e10;
                color: white;
                cursor: pointer;
            }
            button:hover {
                background: #78a317;
            }
            .grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
                gap: 20px;
                margin-top: 20px;
            }
            .card {
                background: #16202d;
                padding: 15px;
                border-radius: 8px;
                border: 1px solid #2a475e;
                text-align: center;
            }
            .card img {
                max-width: 100%;
                border-radius: 4px;
                height: auto;
            }
            .card h3 {
                font-size: 16px;
                margin: 10px 0;
                height: 40px;
                overflow: hidden;
            }
            .playtime {
                font-size: 12px;
                color: #8f98a0;
                margin-bottom: 10px;
            }
            select {
                padding: 5px;
                width: 100%;
                background: #2a475e;
                color: white;
                border: none;
                border-radius: 4px;
            }
            .error-message {
                color: #f06a6a;
                margin-bottom: 10px;
            }
            .status-message {
                color: #66c0f4;
                margin-bottom: 10px;
            }
        </style>
    </head>
    <body>
        <h1>🎮 Мій Ігровий Трекер</h1>

        <div class="auth-box">
            {% if logged_in_steam_id %}
                <div class="logged-in">✅ Увійшов: <strong>{{ logged_in_steam_id }}</strong></div>
                <form method="post" action="/logout">
                    <button type="submit">Вийти</button>
                </form>
            {% else %}
                <div class="auth-box">
                    <input type="text" id="steamIdInput" placeholder="Введіть SteamID" required>
                    <button type="button" id="loginButton" onclick="loginSteam()">Увійти</button>
                </div>
            {% endif %}
        </div>

        <div id="statusMessage" class="status-message"></div>
        <div class="error-message" id="errorMessage"></div>
        <div class="grid" id="gamesGrid"></div>

        <script>
            let currentSteamId = "";

            function showStatus(message, isError = false) {
                const status = document.getElementById('statusMessage');
                const error = document.getElementById('errorMessage');
                status.textContent = message;
                error.textContent = '';
                status.style.color = isError ? '#f06a6a' : '#66c0f4';
            }

            async function loginSteam() {
                const steamId = document.getElementById('steamIdInput').value.trim();
                if (!steamId) {
                    return alert('Будь ласка, введіть SteamID.');
                }

                try {
                    const response = await fetch('/api/login-steam', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ steam_id: steamId })
                    });

                    const data = await response.json();

                    if (data.status === 'success') {
                        showStatus('Увійшов: ' + steamId);
                        loadGames();
                    } else {
                        showStatus(data.message || 'Помилка входу.', true);
                    }
                } catch (err) {
                    showStatus('Помилка при спробі входу: ' + err.message, true);
                }
            }

            async function loadGames() {
                const steamId = document.getElementById('steamIdInput')?.value.trim();
                if (!steamId) {
                    alert('Будь ласка, введіть SteamID.');
                    return;
                }

                currentSteamId = steamId;
                const grid = document.getElementById('gamesGrid');
                if (!grid) {
                    showStatus('Помилка інтерфейсу: елемент ігор не знайдено.', true);
                    return;
                }

                showStatus('Завантаження ігор...');

                try {
                    const response = await fetch('/api/games/' + encodeURIComponent(steamId));
                    const games = await response.json();

                    if (games.error) {
                        showStatus('Помилка сервера: ' + games.error, true);
                        grid.innerHTML = '';
                        return;
                    }

                    if (games.length === 0) {
                        showStatus('Ігри не знайдено.');
                    } else {
                        showStatus('Отримано ігор: ' + games.length);
                    }

                    grid.innerHTML = '';

                    if (!games.length) {
                        const empty = document.createElement('div');
                        empty.className = 'loading';
                        empty.textContent = 'Ігри не знайдено.';
                        grid.appendChild(empty);
                        return;
                    }

                    games.forEach(game => {
                        let optionsHtml = '<option value="">Без оцінки</option>';

                        for (let num = 10; num >= 1; num--) {
                            let selected = "";
                            if (game.rating == num) {
                                selected = "selected";
                            }
                            optionsHtml += '<option value="' + num + '" ' + selected + '>⭐ ' + num + '/10</option>';
                        }

                        const card = document.createElement('div');
                        card.className = 'card';
                        card.innerHTML = `
                            <img src="${game.image}" alt="${game.name}">
                            <h3>${game.name}</h3>
                            <div class="playtime">Час у грі: ${game.playtime} год.</div>
                            <select onchange="rateGame('${game.id}', this.value)">
                                ${optionsHtml}
                            </select>
                        `;
                        grid.appendChild(card);
                    });
                } catch (err) {
                    showStatus('Помилка при завантаженні ігор: ' + err.message, true);
                    grid.innerHTML = '';
                }
            }

            async function rateGame(gameId, rating) {
                if (!gameId) return;

                const action = rating ? 'Оцінка' : 'Видалення оцінки';
                if (!confirm(`${action} для гри ${gameId}?`)) {
                    return;
                }

                try {
                    await fetch('/api/rate', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ game_id: gameId, rating: rating })
                    });
                    loadGames();
                } catch (err) {
                    alert('Помилка при збереженні оцінки: ' + err.message);
                }
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(html_template)


@app.route("/logout", methods=["POST"])
def logout():
    flask_session.pop("steam_id", None)
    return redirect(url_for("index"))


@app.route("/api/login-steam", methods=["POST"])
def login_steam():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"status": "error", "message": "Не вдалося прочитати JSON-тіло запиту."}), 400

    steam_id = data.get("steam_id")
    steam_id_from_form = request.form.get("steam_id")

    if steam_id is None:
        steam_id = steam_id_from_form

    if not steam_id:
        return jsonify({"status": "error", "message": "Поле steam_id відсутнє."}), 400

    steam_id = str(steam_id).strip()

    if not steam_id:
        return jsonify({"status": "error", "message": "SteamID не може бути порожнім."}), 400

    sessions = load_sessions()

    if str(steam_id) not in sessions:
        sessions[str(steam_id)] = {
            "created_at": int(time.time()),
            "uses": 1
        }
        save_sessions(sessions)

    flask_session["steam_id"] = steam_id

    return jsonify({"status": "success", "steam_id": steam_id})


@app.route("/api/games/<steam_id>")
def get_games(steam_id):
    if not flask_session.get("steam_id"):
        return jsonify({"error": "Авторизація необхідна."}), 403

    if str(steam_id) != flask_session["steam_id"]:
        return jsonify({"error": "Недійсний SteamID."}), 403

    games = fetch_steam_games(steam_id)
    return jsonify(games)


@app.route("/api/rate", methods=["POST"])
def rate_game():
    if not flask_session.get("steam_id"):
        return jsonify({"status": "error", "message": "Авторизація необхідна."}), 403

    data = request.get_json(silent=True)

    if not data:
        return jsonify({"status": "error", "message": "Не вдалося прочитати JSON-тіло запиту."}), 400

    game_id = data.get("game_id")
    rating = data.get("rating")

    if game_id is None:
        return jsonify({"status": "error", "message": "Поле game_id відсутнє."}), 400

    if rating is None:
        return jsonify({"status": "error", "message": "Поле rating відсутнє."}), 400

    if not isinstance(rating, int) or isinstance(rating, bool) or not (1 <= rating <= 10):
        return jsonify({"status": "error", "message": "Оцінка має бути цілим числом від 1 до 10."}), 400

    ratings = load_ratings()
    ratings[game_id] = rating
    save_ratings(ratings)

    return jsonify({"status": "success"})


if __name__ == "__main__":
    sessions = load_sessions()

    for steam_id in sessions:
        if not isinstance(sessions[steam_id], dict):
            sessions[steam_id] = {
                "created_at": int(time.time()),
                "uses": 1
            }

    save_sessions(sessions)

    app.run(host="0.0.0.0", port=5000, debug=False)
