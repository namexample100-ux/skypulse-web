import json
import os
from database import SessionLocal, User, Favorite, init_db

def migrate():
    init_db()
    db = SessionLocal()

    # Load Settings
    settings = {}
    if os.path.exists("settings.json"):
        with open("settings.json", "r", encoding="utf-8") as f:
            settings = json.load(f)

    # Load Favorites
    favs = {}
    if os.path.exists("favs.json"):
        with open("favs.json", "r", encoding="utf-8") as f:
            favs = json.load(f)

    # Combine and save
    try:
        for uid_str, s in settings.items():
            uid = int(uid_str)
            user = db.query(User).filter(User.id == uid).first()
            if not user:
                user = User(
                    id=uid,
                    home_city=s.get("home_city"),
                    units=s.get("units", "metric"),
                    lang=s.get("lang", "ru"),
                    news_sources=json.dumps(s.get("news_sources", []))
                )
                db.add(user)
                db.flush() # Get user ID for relationship

            # Add favorites
            user_favs = favs.get(uid_str, [])
            for city in user_favs:
                fav = db.query(Favorite).filter(Favorite.user_id == uid, Favorite.city_name == city).first()
                if not fav:
                    db.add(Favorite(city_name=city, user_id=uid))
        
        db.commit()
        print("Migration successful.")
    except Exception as e:
        db.rollback()
        print(f"Migration failed: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    migrate()
