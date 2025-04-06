from app import app, db, User
from werkzeug.security import generate_password_hash

def create_admin():
    with app.app_context():
        # Önce mevcut admin kullanıcısını kontrol et
        admin = User.query.filter_by(username='admin').first()
        if admin:
            print("Admin kullanıcısı zaten mevcut.")
            return
        
        # Yeni admin kullanıcısı oluştur
        admin = User(
            username='admin',
            email='admin@example.com',
            password=generate_password_hash('admin123'),
            first_name='Admin',
            last_name='User',
            is_admin=True,
            is_active=True
        )
        
        try:
            db.session.add(admin)
            db.session.commit()
            print("Admin kullanıcısı başarıyla oluşturuldu!")
            print("Kullanıcı adı: admin")
            print("Şifre: admin123")
        except Exception as e:
            db.session.rollback()
            print(f"Hata oluştu: {str(e)}")

if __name__ == "__main__":
    create_admin() 