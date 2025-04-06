# İş Akışı Yönetim Sistemi

Bu proje, tekstil perakende sektörü için geliştirilmiş bir iş akışı yönetim sistemidir. Sistem, iş adımlarını takip etmeyi, ekipleri yönetmeyi ve projelerin zaman planlamasını yapmayı sağlar.

## Özellikler

- İş adımlarını belirleme ve yönetme
- Ekip ve çalışan atamaları
- Bağımlılık yönetimi
- Otomatik takvim oluşturma
- Excel'e aktarma
- E-posta bildirimleri

## Kurulum

1. Gerekli Python paketlerini yükleyin:
```bash
pip install -r requirements.txt
```

2. Veritabanını oluşturun:
```bash
python app.py
```

3. Uygulamayı başlatın:
```bash
python app.py
```

## Kullanım

1. Tarayıcınızda `http://localhost:5000` adresine gidin
2. Giriş yapın veya yeni bir hesap oluşturun
3. İş adımlarını ekleyin ve yönetin
4. Excel'e aktarma özelliğini kullanarak raporlar oluşturun

## Gereksinimler

- Python 3.8 veya üzeri
- Flask
- SQLite
- Pandas
- OpenPyXL

## Güvenlik

- E-posta gönderimi için Gmail SMTP kullanılmaktadır
- Kullanıcı kimlik doğrulaması için Flask-Login kullanılmaktadır
- Şifreler güvenli bir şekilde hashlenerek saklanmaktadır

## Lisans

Bu proje MIT lisansı altında lisanslanmıştır. 