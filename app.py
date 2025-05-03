from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_mail import Mail, Message
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import pandas as pd
import os
import secrets
import holidays
from sqlalchemy.orm import relationship
from flask_migrate import Migrate
import logging
from logging.handlers import RotatingFileHandler

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'gizli-anahtar-buraya')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///workflow.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False  # Uyarıyı kaldırmak için eklendi
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', '587'))
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'true').lower() in ['true', 'on', '1']
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', 'omeraydin1990@gmail.com')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', 'uycx mdhi lbom efzo')
app.config['MAIL_DEFAULT_SENDER'] = 'omeraydin1990@gmail.com'

db = SQLAlchemy(app)
migrate = Migrate(app, db)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
mail = Mail(app)

# İş adımları arasındaki bağımlılıkları tutacak ara tablo
work_step_dependencies = db.Table('work_step_dependencies',
    db.Column('dependent_step_id', db.Integer, db.ForeignKey('work_step.id', use_alter=True, name='fk_dependent_step'), primary_key=True),
    db.Column('prerequisite_step_id', db.Integer, db.ForeignKey('work_step.id', use_alter=True, name='fk_prerequisite_step'), primary_key=True)
)

class WorkStepTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    duration = db.Column(db.Integer, nullable=False)
    sequence_number = db.Column(db.Integer, nullable=False)
    is_reference = db.Column(db.Boolean, default=False)
    reference_end_date = db.Column(db.DateTime)
    assigned_team = db.Column(db.String(80))
    assigned_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    process_template_id = db.Column(db.Integer, db.ForeignKey('process_template.id'), nullable=False)

class ProcessTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    work_steps = db.relationship('WorkStepTemplate', backref='process_template', lazy=True, 
                               order_by='WorkStepTemplate.sequence_number')

class Process(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reference_step_id = db.Column(db.Integer, db.ForeignKey('work_step.id', use_alter=True))
    reference_step = db.relationship('WorkStep', foreign_keys=[reference_step_id], post_update=True)
    work_steps = db.relationship('WorkStep', backref='process', lazy=True, 
                               foreign_keys='WorkStep.process_id',
                               order_by='WorkStep.sequence_number')

    def get_total_duration_before_reference(self, step):
        total = 0
        for s in sorted(self.work_steps, key=lambda x: x.sequence_number):
            if s.sequence_number <= step.sequence_number:
                total += s.duration
            if s.is_reference:
                break
        return total

    def get_total_duration_after_reference(self, step):
        total = 0
        found_reference = False
        for s in sorted(self.work_steps, key=lambda x: x.sequence_number):
            if s.is_reference:
                found_reference = True
                continue
            if found_reference and s.sequence_number <= step.sequence_number:
                total += s.duration
        return total

class WorkStep(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    duration = db.Column(db.Integer, nullable=False)  # Gün cinsinden
    process_id = db.Column(db.Integer, db.ForeignKey('process.id', name='fk_process_id'), nullable=False)
    sequence_number = db.Column(db.Integer, nullable=False)  # Süreç akışındaki sıra numarası
    assigned_team = db.Column(db.String(80))  # Ekip ataması
    assigned_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))  # Kullanıcı ataması
    start_date = db.Column(db.DateTime)
    end_date = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='pending')
    completed_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    completed_at = db.Column(db.DateTime)
    is_reference = db.Column(db.Boolean, default=False)  # Referans iş adımı mı?
    reference_end_date = db.Column(db.DateTime)  # Referans bitiş tarihi
    
    # Bağımlılık ilişkileri
    prerequisites = db.relationship(
        'WorkStep', secondary=work_step_dependencies,
        primaryjoin=(id == work_step_dependencies.c.dependent_step_id),
        secondaryjoin=(id == work_step_dependencies.c.prerequisite_step_id),
        backref=db.backref('dependent_steps', lazy='dynamic'),
        lazy='dynamic'
    )

# Ekip üyeleri için ara tablo
team_members = db.Table('team_members',
    db.Column('team_id', db.Integer, db.ForeignKey('team.id', ondelete='CASCADE')),
    db.Column('user_id', db.Integer, db.ForeignKey('user.id', ondelete='CASCADE')),
    db.Column('added_at', db.DateTime, default=datetime.utcnow),
    db.Column('added_by_id', db.Integer, db.ForeignKey('user.id', ondelete='SET NULL')),
    db.UniqueConstraint('team_id', 'user_id', name='unique_team_member')
)

class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(500))
    parent_type = db.Column(db.String(100))  # Üst Ekip (organizasyonel grup)
    team_category = db.Column(db.String(100))  # Ekip (çalışma birimi)
    parent_id = db.Column(db.Integer, db.ForeignKey('team.id', ondelete='SET NULL'))
    leader_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'))
    
    parent = db.relationship('Team', remote_side=[id], backref='sub_teams')
    leader = db.relationship('User', foreign_keys=[leader_id], backref='led_teams')
    members = db.relationship(
        'User',
        secondary=team_members,
        primaryjoin="Team.id==team_members.c.team_id",
        secondaryjoin="User.id==team_members.c.user_id",
        backref=db.backref('teams', lazy='dynamic'),
        lazy='dynamic',
        foreign_keys=[team_members.c.team_id, team_members.c.user_id]
    )

    def get_all_members(self):
        """Ekibin ve alt ekiplerinin tüm üyelerini döndürür"""
        all_members = set(self.members.all())
        for sub_team in self.sub_teams:
            all_members.update(sub_team.get_all_members())
        return list(all_members)

    def get_all_sub_teams(self):
        """Ekibin tüm alt ekiplerini döndürür"""
        all_teams = []
        for sub_team in self.sub_teams:
            all_teams.append(sub_team)
            all_teams.extend(sub_team.get_all_sub_teams())
        return all_teams

    def get_members_by_type(self, team_type):
        """Belirli bir ekip türüne ait tüm üyeleri döndürür"""
        members = set()
        if self.parent_type == team_type:
            members.update(self.members.all())
        for sub_team in self.sub_teams:
            members.update(sub_team.get_members_by_type(team_type))
        return list(members)

    @staticmethod
    def get_hierarchical_teams():
        # Önce üst ekipleri al (parent_id'si None olanlar)
        parent_teams = Team.query.filter_by(parent_id=None).order_by(Team.name).all()
        
        hierarchical_teams = []
        for parent in parent_teams:
            # Üst ekibi ekle
            hierarchical_teams.append({
                'id': parent.id,
                'name': parent.name,
                'is_parent': True
            })
            
            # Alt ekipleri al ve ekle
            sub_teams = Team.query.filter_by(parent_id=parent.id).order_by(Team.name).all()
            for sub_team in sub_teams:
                hierarchical_teams.append({
                    'id': sub_team.id,
                    'name': sub_team.name,
                    'is_parent': False
                })
        
        return hierarchical_teams

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    is_active = db.Column(db.Boolean, default=False)
    activation_token = db.Column(db.String(100), unique=True)
    created_teams = db.relationship('Team', backref='creator', lazy=True, overlaps="leader,led_teams")
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # İlişkiler
    work_steps = db.relationship('WorkStep', backref='assigned_user', lazy=True, foreign_keys=[WorkStep.assigned_user_id])
    completed_steps = db.relationship('WorkStep', backref='completed_by', lazy=True, foreign_keys=[WorkStep.completed_by_id])
    processes = db.relationship('Process', backref='created_by', lazy=True, foreign_keys=[Process.created_by_id])
    process_templates = db.relationship('ProcessTemplate', backref='created_by', lazy=True, foreign_keys=[ProcessTemplate.created_by_id])

    def get_all_teams(self):
        """Kullanıcının üye olduğu tüm ekipleri (ana ve alt ekipler) döndürür"""
        all_teams = set(self.teams.all())
        for team in self.teams:
            if team.parent:
                all_teams.add(team.parent)
        return list(all_teams)

    def get_teams_by_type(self, team_type):
        """Kullanıcının belirli bir türdeki tüm ekiplerini döndürür"""
        return [team for team in self.teams if team.parent_type == team_type]

    def has_team_management_permission(self, team_id):
        """Kullanıcının belirtilen ekip üzerinde yönetim yetkisi var mı?"""
        if self.is_admin:
            return True
        
        team = Team.query.get(team_id)
        if not team:
            return False

        # Ekip lideri mi?
        if team.leader_id == self.id:
            return True

        # Üst ekiplerin lideri mi?
        current_team = team.parent
        while current_team:
            if current_team.leader_id == self.id:
                return True
            current_team = current_team.parent

        return False

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Giriş sayfası
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = User.query.filter_by(email=email).first()
        
        if user and user.check_password(password):
            if not user.is_active:
                flash('Hesabınız henüz aktif değil. Lütfen e-posta adresinize gönderilen aktivasyon linkine tıklayın.')
                return redirect(url_for('login'))
            
            login_user(user)
            return redirect(url_for('index'))
        else:
            flash('Geçersiz e-posta adresi veya şifre!')
            
    return render_template('login.html')

# Kayıt sayfası
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        email = request.form.get('email')
        password = request.form.get('password')
        password_confirm = request.form.get('password_confirm')
        
        if password != password_confirm:
            flash('Şifreler eşleşmiyor!')
            return redirect(url_for('register'))
        
        # Kullanıcı var mı kontrol et
        user = User.query.filter_by(email=email).first()
        if user:
            flash('Bu e-posta adresi zaten kayıtlı!')
            return redirect(url_for('register'))
        
        # Yeni kullanıcı oluştur
        new_user = User(first_name=first_name, last_name=last_name, email=email)
        new_user.set_password(password)
        new_user.activation_token = secrets.token_urlsafe(32)
        db.session.add(new_user)
        db.session.commit()
        
        # Aktivasyon maili gönder
        activation_link = url_for('activate_account', 
                                token=new_user.activation_token, 
                                _external=True)
        
        print(f"Aktivasyon linki oluşturuldu: {activation_link}")  # Debug log
        
        try:
            send_invitation_email(email, activation_link, first_name, last_name)
            print(f"Mail gönderme denemesi yapıldı: {email}")  # Debug log
            flash('Kayıt başarılı! Lütfen e-postanızı kontrol edin.')
        except Exception as e:
            print(f"Mail gönderme hatası: {str(e)}")  # Debug log
            flash('Kayıt başarılı ancak aktivasyon maili gönderilemedi.')
            
        return redirect(url_for('login'))
    
    return render_template('register.html')

# Çıkış işlemi
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# Ana sayfa
@app.route('/')
def root():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    return redirect(url_for('login'))

@app.route('/index')
@login_required
def index():
    processes = Process.query.all()
    return render_template('index.html', processes=processes)

def calculate_work_dates(reference_step, all_steps):
    """İş adımları için başlangıç ve bitiş tarihlerini hesaplar"""
    tr_holidays = holidays.TR()  # Türkiye resmi tatilleri
    
    def is_workday(date):
        return date.weekday() < 5 and date not in tr_holidays  # 0-4 arası Pazartesi-Cuma
    
    def add_workdays(start_date, days):
        current_date = start_date
        remaining_days = days
        while remaining_days > 0:
            current_date += timedelta(days=1)
            if is_workday(current_date):
                remaining_days -= 1
        return current_date
    
    def subtract_workdays(end_date, days):
        current_date = end_date
        remaining_days = days
        while remaining_days > 0:
            current_date -= timedelta(days=1)
            if is_workday(current_date):
                remaining_days -= 1
        return current_date
    
    # Referans iş adımından başlayarak tüm tarihleri hesapla
    steps_to_process = [reference_step]
    processed_steps = set()
    
    while steps_to_process:
        current_step = steps_to_process.pop(0)
        if current_step.id in processed_steps:
            continue
            
        processed_steps.add(current_step.id)
        
        # Bağımlı iş adımlarını işle
        dependent_steps = current_step.dependent_steps.all()
        prerequisite_steps = current_step.prerequisites.all()
        
        # Önceki adımların bitiş tarihlerini kontrol et
        latest_prereq_end = None
        if prerequisite_steps:
            prereq_end_dates = [step.end_date for step in prerequisite_steps if step.end_date]
            if prereq_end_dates:
                latest_prereq_end = max(prereq_end_dates)
        
        # Başlangıç tarihini belirle
        if current_step.is_reference:
            current_step.end_date = current_step.end_date
            current_step.start_date = subtract_workdays(current_step.end_date, current_step.duration)
        else:
            if latest_prereq_end:
                current_step.start_date = add_workdays(latest_prereq_end, 1)
                current_step.end_date = add_workdays(current_step.start_date, current_step.duration - 1)
        
        # Bağımlı adımları kuyruğa ekle
        steps_to_process.extend(dependent_steps)
        steps_to_process.extend(prerequisite_steps)

# Süreç oluşturma
@app.route('/add_process', methods=['GET', 'POST'])
@login_required
def add_process():
    if request.method == 'GET':
        teams = Team.get_hierarchical_teams()
        return render_template('add_process.html', teams=teams)
    if request.method == 'POST':
        try:
            print("POST isteği alındı")  # Debug log
            action = request.form.get('action')
            print(f"Action: {action}")  # Debug log
            name = request.form.get('name')
            description = request.form.get('description')
            print(f"Name: {name}, Description: {description}")  # Debug log
            
            # İş adımlarını topla
            work_steps_data = []
            for key in request.form:
                if key.startswith('work_steps[') and key.endswith('][name]'):
                    index = key[11:-7]  # work_steps[X][name] formatından X'i çıkar
                    step_data = {
                        'name': request.form.get(f'work_steps[{index}][name]'),
                        'description': request.form.get(f'work_steps[{index}][description]'),
                        'duration': request.form.get(f'work_steps[{index}][duration]'),
                        'is_reference': request.form.get(f'work_steps[{index}][is_reference]') == 'on',
                        'reference_end_date': request.form.get(f'work_steps[{index}][reference_end_date]'),
                        'assignment_type': request.form.get(f'work_steps[{index}][assignment_type]'),
                        'assigned_team': request.form.get(f'work_steps[{index}][assigned_team]'),
                        'assigned_user_id': request.form.get(f'work_steps[{index}][assigned_user]')
                    }
                    print(f"İş Adımı {index}: {step_data}")  # Debug log
                    work_steps_data.append(step_data)
            
            print(f"Toplam {len(work_steps_data)} iş adımı bulundu")  # Debug log
            
            if action == 'save_template':
                print("Taslak kaydetme işlemi başlatılıyor")  # Debug log
                # Taslak olarak kaydet
                template = ProcessTemplate(
                    name=name,
                    description=description,
                    created_by_id=current_user.id
                )
                db.session.add(template)
                db.session.flush()

                for i, step_data in enumerate(work_steps_data):
                    step = WorkStepTemplate(
                        name=step_data['name'],
                        description=step_data['description'],
                        duration=int(step_data['duration']),
                        sequence_number=i + 1,
                        is_reference=step_data['is_reference'],
                        reference_end_date=datetime.strptime(step_data['reference_end_date'], '%Y-%m-%dT%H:%M') if step_data['reference_end_date'] else None,
                        assigned_team=step_data['assigned_team'] if step_data['assignment_type'] == 'team' else None,
                        assigned_user_id=int(step_data['assigned_user_id']) if step_data['assignment_type'] == 'user' and step_data['assigned_user_id'] else None,
                        process_template_id=template.id
                    )
                    db.session.add(step)

                db.session.commit()
                flash('Süreç taslağı başarıyla kaydedildi.', 'success')
                return redirect(url_for('process_templates'))
            
            elif action == 'create':
                print("Normal süreç oluşturma işlemi başlatılıyor")  # Debug log
                # Normal süreç olarak kaydet
                process = Process(
                    name=name,
                    description=description,
                    created_by_id=current_user.id
                )
                db.session.add(process)
                db.session.flush()
                print(f"Süreç oluşturuldu, ID: {process.id}")  # Debug log

                reference_step = None
                for i, step_data in enumerate(work_steps_data):
                    try:
                        print(f"İş adımı {i+1} oluşturuluyor: {step_data}")  # Debug log
                        step = WorkStep(
                            name=step_data['name'],
                            description=step_data['description'],
                            duration=int(step_data['duration']),
                            process_id=process.id,
                            sequence_number=i + 1,
                            is_reference=step_data['is_reference']
                        )
                        
                        if step_data['assignment_type'] == 'team':
                            step.assigned_team = step_data['assigned_team']
                        elif step_data['assignment_type'] == 'user' and step_data['assigned_user_id']:
                            step.assigned_user_id = int(step_data['assigned_user_id'])
                        
                        if step_data['is_reference'] and step_data['reference_end_date']:
                            step.reference_end_date = datetime.strptime(step_data['reference_end_date'], '%Y-%m-%dT%H:%M')
                            reference_step = step
                        
                        db.session.add(step)
                        print(f"İş adımı {i+1} başarıyla eklendi")  # Debug log
                    except Exception as step_error:
                        print(f"İş adımı {i+1} oluşturulurken hata: {str(step_error)}")  # Debug log
                        raise
                
                try:
                    db.session.commit()
                    print("Tüm değişiklikler başarıyla kaydedildi")  # Debug log
                    flash('Süreç başarıyla oluşturuldu.', 'success')
                    return redirect(url_for('index'))
                except Exception as commit_error:
                    print(f"Commit sırasında hata: {str(commit_error)}")  # Debug log
                    raise

        except Exception as e:
            db.session.rollback()
            print(f"Genel hata: {str(e)}")  # Debug log
            print(f"Hata türü: {type(e)}")  # Debug log
            import traceback
            print(f"Hata detayı:\n{traceback.format_exc()}")  # Debug log
            flash(f'Bir hata oluştu: {str(e)}', 'danger')
            return redirect(url_for('add_process'))

    users = User.query.all()
    teams = Team.query.all()  # Tüm ekipleri getir
    return render_template('add_process.html', users=users, teams=teams)

# Süreç detay sayfası
@app.route('/process/<int:id>')
@login_required
def process_detail(id):
    process = Process.query.get_or_404(id)
    work_steps = WorkStep.query.filter_by(process_id=id).order_by(WorkStep.sequence_number).all()
    users = User.query.all()
    return render_template('process_detail.html', process=process, work_steps=work_steps, users=users)

# İş adımı ekleme (güncellendi)
@app.route('/add_workstep/<int:process_id>', methods=['GET', 'POST'])
@login_required
def add_workstep(process_id):
    process = Process.query.get_or_404(process_id)
    if request.method == 'POST':
        # Sıra numarasını belirle
        last_step = WorkStep.query.filter_by(process_id=process_id).order_by(WorkStep.sequence_number.desc()).first()
        sequence_number = (last_step.sequence_number + 1) if last_step else 1
        
        new_step = WorkStep(
            name=request.form['name'],
            description=request.form['description'],
            duration=int(request.form['duration']),
            process_id=process_id,
            sequence_number=sequence_number
        )
        
        # Ekip veya kullanıcı ataması
        if request.form.get('assignment_type') == 'team':
            new_step.assigned_team = request.form['team']
        elif request.form.get('assignment_type') == 'user':
            new_step.assigned_user_id = int(request.form['user'])
        
        db.session.add(new_step)
        db.session.commit()
        
        flash('İş adımı başarıyla eklendi.', 'success')
        return redirect(url_for('process_detail', id=process_id))
    
    users = User.query.all()
    return render_template('add_workstep.html', process=process, users=users)

# İş adımı tamamlama
@app.route('/complete_workstep/<int:id>', methods=['POST'])
@login_required
def complete_workstep(id):
    work_step = WorkStep.query.get_or_404(id)
    
    # Yetki kontrolü
    if (work_step.assigned_user_id and work_step.assigned_user_id != current_user.id) or \
       (work_step.assigned_team and work_step.assigned_team != current_user.team):
        flash('Bu iş adımını tamamlama yetkiniz yok.', 'danger')
        return redirect(url_for('process_detail', id=work_step.process_id))
    
    work_step.status = 'completed'
    work_step.completed_by_id = current_user.id
    work_step.completed_at = datetime.utcnow()
    db.session.commit()
    
    flash('İş adımı başarıyla tamamlandı.', 'success')
    return redirect(url_for('process_detail', id=work_step.process_id))

# İş adımı düzenleme
@app.route('/edit_workstep/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_workstep(id):
    work_step = WorkStep.query.get_or_404(id)
    
    if request.method == 'POST':
        work_step.name = request.form['name']
        work_step.description = request.form['description']
        work_step.duration = int(request.form['duration'])
        work_step.assigned_team = request.form['team']
        work_step.status = request.form['status']
        
        if request.form.get('target_date'):
            target_date = datetime.strptime(request.form['target_date'], '%Y-%m-%d')
            work_step.end_date = target_date
            work_step.start_date = target_date - timedelta(days=work_step.duration)
        
        db.session.commit()
        flash('İş adımı başarıyla güncellendi.', 'success')
        return redirect(url_for('process_detail', id=work_step.process_id))
        
    return render_template('edit_workstep.html', work_step=work_step)

# İş adımı silme
@app.route('/delete_workstep/<int:id>')
@login_required
def delete_workstep(id):
    work_step = WorkStep.query.get_or_404(id)
    db.session.delete(work_step)
    db.session.commit()
    flash('İş adımı başarıyla silindi.', 'success')
    return redirect(url_for('process_detail', id=work_step.process_id))

# Excel'e aktarma
@app.route('/export_excel')
@login_required
def export_excel():
    work_steps = WorkStep.query.all()
    data = []
    for step in work_steps:
        data.append({
            'İş Adımı': step.name,
            'Açıklama': step.description,
            'Süre (Gün)': step.duration,
            'Atanan Ekip': step.assigned_team,
            'Başlangıç Tarihi': step.start_date,
            'Bitiş Tarihi': step.end_date,
            'Durum': step.status
        })
    
    df = pd.DataFrame(data)
    excel_file = 'workflow_export.xlsx'
    df.to_excel(excel_file, index=False)
    return send_file(excel_file, as_attachment=True)

def send_notification_email(work_step):
    user = User.query.get(work_step.assigned_user_id)
    if user and user.email:
        msg = Message('Yeni İş Adımı Eklendi',
                    sender='omeraydin1990@gmail.com',
                    recipients=[user.email])
        msg.body = f'Yeni bir iş adımı eklendi: {work_step.name}'
        try:
            mail.send(msg)
        except Exception as e:
            print(f"E-posta gönderirken hata oluştu: {e}")

@app.route('/edit_process/<int:process_id>', methods=['GET', 'POST'])
@login_required
def edit_process(process_id):
    process = Process.query.get_or_404(process_id)
    users = User.query.all()
    
    if request.method == 'POST':
        try:
            action = request.form.get('action')
            name = request.form.get('name')
            description = request.form.get('description')
            
            # İş adımlarını topla
            work_steps_data = []
            for key in request.form:
                if key.startswith('work_steps[') and key.endswith('][name]'):
                    index = key[11:-7]
                    step_data = {
                        'name': request.form.get(f'work_steps[{index}][name]'),
                        'description': request.form.get(f'work_steps[{index}][description]'),
                        'duration': request.form.get(f'work_steps[{index}][duration]'),
                        'is_reference': request.form.get(f'work_steps[{index}][is_reference]') == 'on',
                        'reference_end_date': request.form.get(f'work_steps[{index}][reference_end_date]'),
                        'assignment_type': request.form.get(f'work_steps[{index}][assignment_type]'),
                        'assigned_team': request.form.get(f'work_steps[{index}][assigned_team]'),
                        'assigned_user_id': request.form.get(f'work_steps[{index}][assigned_user]')
                    }
                    work_steps_data.append(step_data)

            if action == 'save_template':
                print("Taslak olarak kaydetme işlemi başlatılıyor")  # Debug log
                # Taslak olarak kaydet
                template = ProcessTemplate(
                    name=name,
                    description=description,
                    created_by_id=current_user.id
                )
                db.session.add(template)
                db.session.flush()
                print(f"Template oluşturuldu, ID: {template.id}")  # Debug log

                for i, step_data in enumerate(work_steps_data):
                    try:
                        print(f"İş adımı {i+1} oluşturuluyor: {step_data}")  # Debug log
                        step = WorkStepTemplate(
                            name=step_data['name'],
                            description=step_data['description'],
                            duration=int(step_data['duration']),
                            sequence_number=i + 1,
                            is_reference=step_data['is_reference'],
                            reference_end_date=datetime.strptime(step_data['reference_end_date'], '%Y-%m-%dT%H:%M') if step_data['reference_end_date'] else None,
                            assigned_team=step_data['assigned_team'] if step_data['assignment_type'] == 'team' else None,
                            assigned_user_id=int(step_data['assigned_user_id']) if step_data['assignment_type'] == 'user' and step_data['assigned_user_id'] else None,
                            process_template_id=template.id
                        )
                        db.session.add(step)
                        print(f"İş adımı {i+1} başarıyla eklendi")  # Debug log
                    except Exception as step_error:
                        print(f"İş adımı {i+1} oluşturulurken hata: {str(step_error)}")  # Debug log
                        raise

                try:
                    db.session.commit()
                    print("Tüm değişiklikler başarıyla kaydedildi")  # Debug log
                    flash('Süreç taslağı başarıyla kaydedildi.', 'success')
                    return redirect(url_for('process_templates'))
                except Exception as commit_error:
                    print(f"Commit sırasında hata: {str(commit_error)}")  # Debug log
                    raise

            else:
                # Süreci güncelle
                process.name = name
                process.description = description
                
                # Mevcut iş adımlarını temizle
                WorkStep.query.filter_by(process_id=process.id).delete()
                
                # Yeni iş adımlarını ekle
                reference_step = None
                for i, step_data in enumerate(work_steps_data):
                    step = WorkStep(
                        name=step_data['name'],
                        description=step_data['description'],
                        duration=int(step_data['duration']),
                        process_id=process.id,
                        sequence_number=i + 1,
                        is_reference=step_data['is_reference']
                    )
                    
                    if step_data['assignment_type'] == 'team':
                        step.assigned_team = step_data['assigned_team']
                    elif step_data['assignment_type'] == 'user' and step_data['assigned_user_id']:
                        step.assigned_user_id = int(step_data['assigned_user_id'])
                    
                    if step_data['is_reference'] and step_data['reference_end_date']:
                        step.reference_end_date = datetime.strptime(step_data['reference_end_date'], '%Y-%m-%dT%H:%M')
                        reference_step = step
                    
                    db.session.add(step)
                
                db.session.commit()
                flash('Süreç başarıyla güncellendi.', 'success')
                return redirect(url_for('index'))
            
        except Exception as e:
            db.session.rollback()
            print(f"Genel hata: {str(e)}")  # Debug log
            print(f"Hata türü: {type(e)}")  # Debug log
            import traceback
            print(f"Hata detayı:\n{traceback.format_exc()}")  # Debug log
            flash(f'Bir hata oluştu: {str(e)}', 'danger')
            return redirect(url_for('edit_process', process_id=process_id))
    
    return render_template('add_process.html', edit_mode=True, process=process, users=users)

@app.route('/process_templates')
@login_required
def process_templates():
    try:
        templates = ProcessTemplate.query.filter_by(created_by_id=current_user.id).all()
        print(f"Bulunan taslak sayısı: {len(templates)}")  # Debug log
        for template in templates:
            print(f"Taslak: {template.name}, Oluşturan: {template.created_by.username}")  # Debug log
        return render_template('process_templates.html', templates=templates)
    except Exception as e:
        print(f"Hata: {str(e)}")  # Debug log
        flash('Taslaklar yüklenirken bir hata oluştu.', 'danger')
        return redirect(url_for('index'))

@app.route('/templates/add', methods=['GET', 'POST'])
@login_required
def add_template():
    if request.method == 'POST':
        try:
            template = ProcessTemplate(
                name=request.form.get('name'),
                description=request.form.get('description'),
                created_by_id=current_user.id
            )
            db.session.add(template)

            work_steps_data = []
            for key, value in request.form.items():
                if key.startswith('work_steps[') and key.endswith('][name]'):
                    index = key[11:-7]  # work_steps[X][name] -> X
                    work_steps_data.append({
                        'index': index,
                        'name': request.form.get(f'work_steps[{index}][name]'),
                        'duration': request.form.get(f'work_steps[{index}][duration]'),
                        'is_reference': request.form.get(f'work_steps[{index}][is_reference]') == 'on',
                        'assigned_team': request.form.get(f'work_steps[{index}][assigned_team]'),
                        'assigned_user_id': request.form.get(f'work_steps[{index}][assigned_user]')
                    })

            for i, step_data in enumerate(work_steps_data):
                step = WorkStepTemplate(
                    name=step_data['name'],
                    description=step_data['description'],
                    duration=step_data['duration'],
                    sequence_number=i + 1,
                    is_reference=step_data['is_reference'],
                    reference_end_date=datetime.strptime(step_data['reference_end_date'], '%Y-%m-%dT%H:%M') if step_data['reference_end_date'] else None,
                    assigned_team=step_data['assigned_team'],
                    assigned_user_id=step_data['assigned_user_id'] if step_data['assigned_user_id'] else None
                )
                template.work_steps.append(step)

            db.session.commit()
            flash('Süreç taslağı başarıyla oluşturuldu.', 'success')
            return redirect(url_for('process_templates'))
        except Exception as e:
            db.session.rollback()
            flash(f'Süreç taslağı oluşturulurken bir hata oluştu: {str(e)}', 'danger')
            return redirect(url_for('add_template'))

    users = User.query.all()
    return render_template('add_template.html', users=users)

@app.route('/templates/<int:id>/use', methods=['GET', 'POST'])
@login_required
def use_template(id):
    template = ProcessTemplate.query.get_or_404(id)
    if request.method == 'POST':
        try:
            process = Process(
                name=request.form.get('name'),
                description=request.form.get('description'),
                created_by_id=current_user.id
            )
            db.session.add(process)
            db.session.flush()  # process.id'yi almak için flush yapıyoruz

            reference_step = None
            for template_step in template.work_steps:
                step = WorkStep(
                    name=template_step.name,
                    description=template_step.description,
                    duration=template_step.duration,
                    sequence_number=template_step.sequence_number,
                    is_reference=template_step.is_reference,
                    assigned_team=template_step.assigned_team,
                    assigned_user_id=template_step.assigned_user_id,
                    process_id=process.id
                )
                
                if step.is_reference:
                    # Form'dan gelen referans tarihini kullan
                    reference_end_date = request.form.get(f'work_steps[{template_step.sequence_number-1}][reference_end_date]')
                    if reference_end_date:
                        step.reference_end_date = datetime.strptime(reference_end_date, '%Y-%m-%dT%H:%M')
                    reference_step = step
                
                db.session.add(step)

            if reference_step:
                process.reference_step_id = reference_step.id

            db.session.commit()
            flash('Süreç başarıyla oluşturuldu.', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            db.session.rollback()
            flash(f'Süreç oluşturulurken bir hata oluştu: {str(e)}', 'danger')
            return redirect(url_for('use_template', id=id))

    return render_template('use_template.html', template=template)

@app.route('/delete_process/<int:process_id>', methods=['POST'])
@login_required
def delete_process(process_id):
    process = Process.query.get_or_404(process_id)
    
    # Sadece süreci oluşturan kullanıcı silebilir
    if process.created_by_id != current_user.id:
        flash('Bu süreci silme yetkiniz yok.', 'error')
        return redirect(url_for('index'))
    
    try:
        # İş adımlarını sil
        for step in process.work_steps:
            db.session.delete(step)
        
        # Süreci sil
        db.session.delete(process)
        db.session.commit()
        
        flash('Süreç başarıyla silindi.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Süreç silinirken bir hata oluştu.', 'error')
    
    return redirect(url_for('index'))

@app.route('/view_process/<int:process_id>')
@login_required
def view_process(process_id):
    process = Process.query.get_or_404(process_id)
    return render_template('process_detail.html', process=process)

@app.route('/edit_template/<int:template_id>', methods=['GET', 'POST'])
@login_required
def edit_template(template_id):
    template = ProcessTemplate.query.get_or_404(template_id)
    users = User.query.all()
    
    if request.method == 'POST':
        try:
            action = request.form.get('action')
            name = request.form.get('name')
            description = request.form.get('description')
            
            # İş adımlarını topla
            work_steps_data = []
            for key in request.form:
                if key.startswith('work_steps[') and key.endswith('][name]'):
                    index = key[11:-7]
                    step_data = {
                        'name': request.form.get(f'work_steps[{index}][name]'),
                        'description': request.form.get(f'work_steps[{index}][description]'),
                        'duration': request.form.get(f'work_steps[{index}][duration]'),
                        'is_reference': request.form.get(f'work_steps[{index}][is_reference]') == 'on',
                        'reference_end_date': request.form.get(f'work_steps[{index}][reference_end_date]'),
                        'assignment_type': request.form.get(f'work_steps[{index}][assignment_type]'),
                        'assigned_team': request.form.get(f'work_steps[{index}][assigned_team]'),
                        'assigned_user_id': request.form.get(f'work_steps[{index}][assigned_user]')
                    }
                    work_steps_data.append(step_data)

            if action == 'create':
                # Normal süreç olarak kaydet
                process = Process(
                    name=name,
                    description=description,
                    created_by_id=current_user.id
                )
                db.session.add(process)
                db.session.flush()

                reference_step = None
                for i, step_data in enumerate(work_steps_data):
                    step = WorkStep(
                        name=step_data['name'],
                        description=step_data['description'],
                        duration=int(step_data['duration']),
                        process_id=process.id,
                        sequence_number=i + 1,
                        is_reference=step_data['is_reference']
                    )
                    
                    if step_data['assignment_type'] == 'team':
                        step.assigned_team = step_data['assigned_team']
                    elif step_data['assignment_type'] == 'user' and step_data['assigned_user_id']:
                        step.assigned_user_id = int(step_data['assigned_user_id'])
                    
                    if step_data['is_reference'] and step_data['reference_end_date']:
                        step.reference_end_date = datetime.strptime(step_data['reference_end_date'], '%Y-%m-%dT%H:%M')
                        reference_step = step
                    
                    db.session.add(step)

                db.session.commit()
                flash('Süreç başarıyla oluşturuldu.', 'success')
                return redirect(url_for('index'))
            else:
                # Taslağı güncelle
                template.name = name
                template.description = description
                
                # Mevcut iş adımlarını temizle
                WorkStepTemplate.query.filter_by(process_template_id=template.id).delete()
                
                # Yeni iş adımlarını ekle
                for i, step_data in enumerate(work_steps_data):
                    step = WorkStepTemplate(
                        name=step_data['name'],
                        description=step_data['description'],
                        duration=int(step_data['duration']),
                        sequence_number=i + 1,
                        is_reference=step_data['is_reference'],
                        reference_end_date=datetime.strptime(step_data['reference_end_date'], '%Y-%m-%dT%H:%M') if step_data['reference_end_date'] else None,
                        assigned_team=step_data['assigned_team'] if step_data['assignment_type'] == 'team' else None,
                        assigned_user_id=int(step_data['assigned_user_id']) if step_data['assignment_type'] == 'user' and step_data['assigned_user_id'] else None,
                        process_template_id=template.id
                    )
                    db.session.add(step)
                
                db.session.commit()
                flash('Taslak başarıyla güncellendi.', 'success')
                return redirect(url_for('process_templates'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Bir hata oluştu: {str(e)}', 'danger')
            return redirect(url_for('edit_template', template_id=template_id))
    
    return render_template('add_process.html', edit_mode=True, process=template, is_template=True, users=users)

@app.route('/delete_template/<int:template_id>', methods=['POST'])
@login_required
def delete_template(template_id):
    template = ProcessTemplate.query.get_or_404(template_id)
    
    # Sadece taslağı oluşturan kullanıcı silebilir
    if template.created_by_id != current_user.id:
        flash('Bu taslağı silme yetkiniz yok.', 'error')
        return redirect(url_for('process_templates'))
    
    try:
        # İş adımlarını sil
        WorkStepTemplate.query.filter_by(process_template_id=template.id).delete()
        
        # Taslağı sil
        db.session.delete(template)
        db.session.commit()
        
        flash('Taslak başarıyla silindi.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Taslak silinirken bir hata oluştu.', 'error')
    
    return redirect(url_for('process_templates'))

@app.route('/teams')
@login_required
def teams():
    # Kullanıcının lideri olduğu ekipleri getir
    led_teams = Team.query.filter_by(leader_id=current_user.id).all()
    # Kullanıcının üyesi olduğu ekipleri getir ve listeye dönüştür
    member_teams = list(current_user.teams.all())
    # Tüm ekipleri birleştir
    all_teams = list(set(led_teams + member_teams))
    return render_template('teams.html', teams=all_teams)

@app.route('/teams/add', methods=['GET', 'POST'])
@login_required
def add_team():
    """Yeni ekip oluştur"""
    if not current_user.is_admin:
        flash('Bu işlem için yetkiniz yok.', 'danger')
        return redirect(url_for('teams'))

    if request.method == 'POST':
        name = request.form.get('name')
        team_type = request.form.get('team_type')
        description = request.form.get('description')
        parent_id = request.form.get('parent_id')
        leader_id = request.form.get('leader_id')

        team = Team(
            name=name,
            parent_type=team_type,
            description=description
        )
        if parent_id:
            team.parent_id = int(parent_id)
        if leader_id:
            team.leader_id = int(leader_id)

        try:
            db.session.add(team)
            db.session.commit()
            flash('Ekip başarıyla oluşturuldu.', 'success')
            return redirect(url_for('teams'))
        except Exception as e:
            db.session.rollback()
            flash(f'Ekip oluşturulurken bir hata oluştu: {str(e)}', 'danger')

    parent_teams = Team.query.all()
    users = User.query.all()
    return render_template('add_team.html', parent_teams=parent_teams, users=users)

@app.route('/teams/<int:team_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_team(team_id):
    """Ekip düzenle"""
    team = Team.query.get_or_404(team_id)
    
    if not current_user.is_admin and not current_user.has_team_management_permission(team_id):
        flash('Bu işlem için yetkiniz yok.', 'danger')
        return redirect(url_for('teams'))

    if request.method == 'POST':
        name = request.form.get('name')
        team_type = request.form.get('team_type')
        description = request.form.get('description')
        parent_id = request.form.get('parent_id')
        leader_id = request.form.get('leader_id')
        member_ids = request.form.getlist('members')

        try:
            team.name = name
            team.parent_type = team_type
            team.description = description
            team.parent_id = int(parent_id) if parent_id else None
            team.leader_id = int(leader_id) if leader_id else None

            # Ekip üyelerini güncelle
            team.members = []
            for member_id in member_ids:
                user = User.query.get(int(member_id))
                if user:
                    team.members.append(user)

            db.session.commit()
            flash('Ekip başarıyla güncellendi.', 'success')
            return redirect(url_for('teams'))
        except Exception as e:
            db.session.rollback()
            flash(f'Ekip güncellenirken bir hata oluştu: {str(e)}', 'danger')

    parent_teams = Team.query.filter(Team.id != team_id).all()
    users = User.query.all()
    return render_template('add_team.html', team=team, parent_teams=parent_teams, users=users)

@app.route('/teams/<int:team_id>/delete', methods=['POST'])
@login_required
def delete_team(team_id):
    """Ekip sil"""
    team = Team.query.get_or_404(team_id)
    
    if not current_user.is_admin and not current_user.has_team_management_permission(team_id):
        flash('Bu işlem için yetkiniz yok.', 'danger')
        return redirect(url_for('teams'))

    try:
        # Alt ekipleri kontrol et
        if team.sub_teams.count() > 0:
            flash('Bu ekibin alt ekipleri var. Önce alt ekipleri silmelisiniz.', 'danger')
            return redirect(url_for('teams'))

        db.session.delete(team)
        db.session.commit()
        flash('Ekip başarıyla silindi.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ekip silinirken bir hata oluştu: {str(e)}', 'danger')

    return redirect(url_for('teams'))

@app.route('/teams/<int:team_id>/members/<int:user_id>/remove', methods=['POST'])
@login_required
def remove_team_member(team_id, user_id):
    """Ekip üyesini çıkar"""
    team = Team.query.get_or_404(team_id)
    user = User.query.get_or_404(user_id)
    
    if not current_user.is_admin and not current_user.has_team_management_permission(team_id):
        flash('Bu işlem için yetkiniz yok.', 'danger')
        return redirect(url_for('teams'))

    try:
        team.members.remove(user)
        db.session.commit()
        flash('Üye ekipten başarıyla çıkarıldı.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Üye çıkarılırken bir hata oluştu: {str(e)}', 'danger')

    return redirect(url_for('teams'))

@app.route('/invite_user', methods=['GET', 'POST'])
@login_required
def invite_user():
    """Yeni kullanıcı davet et"""
    if not current_user.is_admin:
        flash('Bu işlem için yetkiniz yok.', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = request.form.get('email')
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')

        # E-posta kontrolü
        if User.query.filter_by(email=email).first():
            flash('Bu e-posta adresi zaten kullanılıyor.', 'danger')
            return redirect(url_for('invite_user'))

        # Davet token'ı oluştur
        token = secrets.token_urlsafe(32)
        
        # Yeni kullanıcı oluştur
        new_user = User(
            email=email,
            first_name=first_name,
            last_name=last_name,
            is_active=False,
            activation_token=token,
            invitation_sent_at=datetime.utcnow()
        )
        
        try:
            db.session.add(new_user)
            db.session.commit()
            
            # Aktivasyon linki
            activation_link = url_for('activate_account', token=token, _external=True)
            
            # E-posta gönder
            if send_invitation_email(email, activation_link, first_name, last_name):
                flash('Kullanıcı davet edildi ve aktivasyon e-postası gönderildi.', 'success')
            else:
                flash('Kullanıcı oluşturuldu fakat e-posta gönderilemedi. Lütfen sistem yöneticisine başvurun.', 'warning')
            
            return redirect(url_for('users'))
        except Exception as e:
            db.session.rollback()
            flash(f'Kullanıcı davet edilirken bir hata oluştu: {str(e)}', 'danger')
            return redirect(url_for('invite_user'))

    return render_template('invite_user.html')

@app.route('/activate_account/<token>')
def activate_account(token):
    user = User.query.filter_by(activation_token=token).first()
    if user:
        user.is_active = True
        user.activation_token = None
        db.session.commit()
        flash('Hesabınız başarıyla aktifleştirildi! Şimdi giriş yapabilirsiniz.')
    else:
        flash('Geçersiz veya kullanılmış aktivasyon linki!')
    return redirect(url_for('login'))

@app.route('/users')
@login_required
def users():
    """Kullanıcıları listele"""
    if not current_user.is_admin:
        flash('Bu sayfaya erişim yetkiniz yok.', 'danger')
        return redirect(url_for('index'))
    
    users = User.query.all()
    return render_template('users.html', users=users)

def send_invitation_email(user_email, activation_link, first_name, last_name):
    """Kullanıcıya davet e-postası gönder"""
    try:
        msg = Message('İş Planı - Hesap Aktivasyonu',
                      sender=app.config['MAIL_USERNAME'],
                      recipients=[user_email])
        
        msg.body = f'''Merhaba {first_name} {last_name},

İş Planı uygulamasına hoş geldiniz. Hesabınızı aktifleştirmek için aşağıdaki linke tıklayın:

{activation_link}

Bu link 24 saat içinde geçerliliğini yitirecektir.

İyi çalışmalar,
İş Planı Ekibi'''

        print(f"Mail gönderiliyor: {user_email}")
        mail.send(msg)
        print(f"Mail başarıyla gönderildi: {user_email}")
        return True
    except Exception as e:
        print(f"Mail gönderme hatası: {str(e)}")
        import traceback
        print(f"Hata detayı:\n{traceback.format_exc()}")
        return False

@app.route('/teams/create', methods=['GET', 'POST'])
@login_required
def create_team():
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        
        if not name:
            flash('Ekip adı boş olamaz!')
            return redirect(url_for('create_team'))
        
        # Yeni ekip oluştur
        new_team = Team(
            name=name,
            description=description,
            leader_id=current_user.id
        )
        
        try:
            db.session.add(new_team)
            db.session.commit()
            flash('Ekip başarıyla oluşturuldu!')
            return redirect(url_for('teams'))
        except Exception as e:
            db.session.rollback()
            flash(f'Ekip oluşturulurken bir hata oluştu: {str(e)}')
            return redirect(url_for('create_team'))
    
    return render_template('create_team.html')

# Loglama ayarları
if not os.path.exists('logs'):
    os.mkdir('logs')
file_handler = RotatingFileHandler('logs/app.log', maxBytes=10240, backupCount=10)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
file_handler.setLevel(logging.INFO)
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)
app.logger.info('İş Planı başlatılıyor')

# Veritabanını oluştur
with app.app_context():
    db.create_all()

# PythonAnywhere için WSGI uygulaması
application = app

if __name__ == '__main__':
    # Bu blok sadece lokal geliştirme için kullanılır
    app.run(debug=True) 
