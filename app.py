import os
from flask import Flask, render_template, redirect, url_for, request, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from models import db, User, ServiceRequest

app = Flask(__name__)
app.secret_key = 'campusfix_secret_key'

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///campusfix.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

db.init_app(app)

@app.context_processor
def inject_notifications():
    if 'user_id' in session:
        role = session.get('role')
        user_name = session.get('user_name')
        user_id = session.get('user_id')
        
        if role == 'Administrator':
            count = ServiceRequest.query.filter(ServiceRequest.status != 'Resolved').count()
        elif role == 'Staff':
            count = ServiceRequest.query.filter_by(assigned_to=user_name).filter(ServiceRequest.status != 'Resolved').count()
        else:
            count = ServiceRequest.query.filter_by(user_id=user_id).filter(ServiceRequest.status != 'Resolved').count()
            
        current_user = User.query.get(user_id)
        return dict(notification_count=count, user=current_user)
    return dict(notification_count=0, user=None)

with app.app_context():
    db.create_all()
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    
    admin_email = 'admin@campusfix.com'
    existing_admin = User.query.filter_by(email=admin_email).first()
    if not existing_admin:
        hashed_password = generate_password_hash('admin123')
        default_admin = User(
            name='System Administrator',
            email=admin_email,
            password=hashed_password,
            role='Administrator'
        )
        db.session.add(default_admin)
        db.session.commit()
        print("Default Admin Account Created Successfully!")

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['user_name'] = user.name
            session['role'] = user.role
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid email or password.', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = generate_password_hash(request.form['password'])
        role = request.form['role']
        
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash('Email already registered.', 'danger')
            return redirect(url_for('register'))
            
        new_user = User(name=name, email=email, password=password, role=role)
        db.session.add(new_user)
        db.session.commit()
        
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    role = session.get('role')
    user_id = session.get('user_id')
    user_name = session.get('user_name')
    
    if role == 'Administrator':
        total_users = User.query.count()
        total_requests = ServiceRequest.query.count()
        users = User.query.all()
        return render_template('admin/dashboard.html', total_users=total_users, total_requests=total_requests, users=users)
    elif role == 'Staff':
        total = ServiceRequest.query.filter_by(assigned_to=user_name).count()
        pending = ServiceRequest.query.filter_by(assigned_to=user_name, status='Assigned').count()
        in_progress = ServiceRequest.query.filter_by(assigned_to=user_name, status='In Progress').count()
        resolved = ServiceRequest.query.filter_by(assigned_to=user_name, status='Resolved').count()
        recent_reports = ServiceRequest.query.filter_by(assigned_to=user_name).order_by(ServiceRequest.created_at.desc()).limit(5).all()
        return render_template('staff/dashboard.html', total=total, pending=pending, in_progress=in_progress, resolved=resolved, recent_reports=recent_reports)
    else: 
        total = ServiceRequest.query.filter_by(user_id=user_id).count()
        pending = ServiceRequest.query.filter_by(user_id=user_id, status='Submitted').count()
        in_progress = ServiceRequest.query.filter_by(user_id=user_id, status='In Progress').count()
        resolved = ServiceRequest.query.filter_by(user_id=user_id, status='Resolved').count()
        recent_reports = ServiceRequest.query.filter_by(user_id=user_id).order_by(ServiceRequest.created_at.desc()).limit(5).all()
        return render_template('students/dashboard.html', total=total, pending=pending, in_progress=in_progress, resolved=resolved, recent_reports=recent_reports)

@app.route('/my-reports')
def my_reports():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    role = session.get('role')
    user_id = session.get('user_id')
    user_name = session.get('user_name')
    search_query = request.args.get('q', '')
    
    if role == 'Administrator':
        query = ServiceRequest.query
    elif role == 'Staff':
        query = ServiceRequest.query.filter_by(assigned_to=user_name)
    else: 
        query = ServiceRequest.query.filter_by(user_id=user_id)
        
    if search_query:
        query = query.filter(
            db.or_(
                ServiceRequest.title.ilike(f'%{search_query}%'),
                ServiceRequest.location.ilike(f'%{search_query}%'),
                ServiceRequest.description.ilike(f'%{search_query}%')
            )
        )
        
    reports = query.order_by(ServiceRequest.created_at.desc()).all()
    
    if role == 'Administrator':
        staff_members = User.query.filter_by(role='Staff').all()
        return render_template('admin/reports.html', reports=reports, staff_members=staff_members)
    elif role == 'Staff':
        return render_template('staff/reports.html', reports=reports)
    else: 
        return render_template('students/reports.html', reports=reports)

@app.route('/report-issue', methods=['GET', 'POST'])
def report_issue():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    role = session.get('role')
    if role not in ['Student', 'Staff']:
        flash('Unauthorized action.', 'danger')
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        title = request.form['title']
        priority = request.form['priority']
        location = request.form['location']
        description = request.form['description']
        
        photo_filename = None
        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename != '':
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                photo_filename = filename
                
        new_request = ServiceRequest(
            title=title,
            priority=priority,
            location=location,
            description=description,
            photo=photo_filename,
            user_id=session['user_id'],
            status='Submitted'
        )
        db.session.add(new_request)
        db.session.commit()
        
        flash('Maintenance request submitted successfully!', 'success')
        return redirect(url_for('my_reports'))
        
    if role == 'Staff':
        return render_template('professors/report_issue.html')
    else:
        return render_template('students/report_issue.html')

@app.route('/notifications')
def notifications():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    role = session.get('role')
    user_id = session.get('user_id')
    user_name = session.get('user_name')
    
    if role == 'Administrator':
        notifs = ServiceRequest.query.order_by(ServiceRequest.created_at.desc()).all()
        return render_template('admin/notifications.html', notifications=notifs)
    elif role == 'Staff':
        notifs = ServiceRequest.query.filter_by(assigned_to=user_name).order_by(ServiceRequest.created_at.desc()).all()
        return render_template('staff/notifications.html', notifications=notifs)
    else:
        notifs = ServiceRequest.query.filter_by(user_id=user_id).order_by(ServiceRequest.created_at.desc()).all()
        return render_template('students/notifications.html', notifications=notifs)

@app.route('/report-details/<int:id>')
def report_details(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    report = ServiceRequest.query.get_or_404(id)
    role = session.get('role')
    
    if role == 'Administrator':
        staff_members = User.query.filter_by(role='Staff').all()
        return render_template('admin/report_details.html', report=report, staff_members=staff_members)
    elif role == 'Staff':
        return render_template('staff/report_details.html', report=report)
    else:
        return render_template('students/report_details.html', report=report)

@app.route('/update-request/<int:id>', methods=['POST'])
def update_request(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    report = ServiceRequest.query.get_or_404(id)
    role = session.get('role')
    
    if role == 'Staff':
        report.status = 'Resolved'
        report.resolution_notes = request.form.get('resolution_notes')
    elif role == 'Administrator':
        report.status = request.form.get('status')
        report.assigned_to = request.form.get('assigned_to')
        if report.assigned_to and report.status == 'Submitted':
            report.status = 'Assigned'
        report.resolution_notes = request.form.get('resolution_notes')
        
    db.session.commit()
    flash('Request updated successfully!', 'success')
    return redirect(url_for('my_reports'))

@app.route('/knowledge-base')
def knowledge_base():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('knowledge_base.html')

@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    return render_template('profile.html', user=user)

@app.route('/update-profile', methods=['POST'])
def update_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    user.name = request.form.get('name')
    
    if 'profile_photo' in request.files:
        file = request.files['profile_photo']
        if file and file.filename != '':
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            user.profile_photo = filename
            
    db.session.commit()
    flash('Profile updated successfully!', 'success')
    return redirect(url_for('profile'))

@app.route('/settings')
def settings():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('settings.html')

@app.route('/admin/reports')
def admin_reports():
    if 'user_id' not in session or session.get('role') != 'Administrator':
        return redirect(url_for('login'))
    reports = ServiceRequest.query.order_by(ServiceRequest.created_at.desc()).all()
    total_resolved = ServiceRequest.query.filter_by(status='Resolved').count()
    total_pending = ServiceRequest.query.filter(ServiceRequest.status != 'Resolved').count()
    return render_template('admin/admin_reports.html', reports=reports, total_resolved=total_resolved, total_pending=total_pending)

@app.route('/admin/add-staff', methods=['POST'])
def add_staff():
    if 'user_id' not in session or session.get('role') != 'Administrator':
        return redirect(url_for('login'))
    name = request.form['name']
    email = request.form['email']
    password = generate_password_hash(request.form['password'])
    
    existing = User.query.filter_by(email=email).first()
    if existing:
        flash('Email already exists.', 'danger')
        return redirect(url_for('dashboard'))
        
    new_staff = User(name=name, email=email, password=password, role='Staff')
    db.session.add(new_staff)
    db.session.commit()
    flash('Maintenance staff added successfully!', 'success')
    return redirect(url_for('dashboard'))

@app.route('/admin/update-user-role/<int:id>', methods=['POST'])
def update_user_role(id):
    if 'user_id' not in session or session.get('role') != 'Administrator':
        return redirect(url_for('login'))
    user = User.query.get_or_404(id)
    if user.role != 'Administrator':
        user.role = request.form['role']
        db.session.commit()
        flash('User role updated successfully!', 'success')
    return redirect(url_for('dashboard'))

@app.route('/admin/delete-user/<int:id>', methods=['POST'])
def delete_user(id):
    if 'user_id' not in session or session.get('role') != 'Administrator':
        return redirect(url_for('login'))
    user = User.query.get_or_404(id)
    if user.role != 'Administrator':
        db.session.delete(user)
        db.session.commit()
        flash('User deleted successfully!', 'success')
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    app.run(debug=True)