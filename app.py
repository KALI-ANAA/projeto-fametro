from datetime import date, datetime, timedelta
from functools import wraps

from flask import Flask, flash, redirect, render_template, request, session, url_for
from sqlalchemy import func, inspect, text
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db
from model import ConfiguracaoAgenda, Feriado, Laboratorio, Reserva, Usuario

app = Flask(__name__)
app.config["SECRET_KEY"] = "segredo_super_simples"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///banco.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

ROLE_TECNICO = "tecnico"
ROLE_PROFESSOR = "professor"

TURNOS = [
    ("manha", "Manhã"),
    ("tarde", "Tarde"),
    ("noite", "Noite"),
]

STATUS_LABELS = {
    "pendente": "Pendente",
    "aprovada": "Aprovada",
    "recusada": "Recusada",
    "indisponivel": "Indisponível",
}


def parse_date(raw_value):
    if not raw_value:
        return None
    try:
        return datetime.strptime(raw_value, "%Y-%m-%d").date()
    except ValueError:
        return None


def get_week_start(raw_value=None):
    base_day = parse_date(raw_value) or date.today()
    return base_day - timedelta(days=base_day.weekday())


def get_logged_user():
    user_id = session.get("usuario_id")
    return db.session.get(Usuario, user_id) if user_id else None


def is_password_valid(usuario, senha_digitada):
    if not usuario or not senha_digitada:
        return False

    try:
        if check_password_hash(usuario.senha, senha_digitada):
            return True
    except ValueError:
        pass

    return usuario.senha == senha_digitada


def upgrade_legacy_password_if_needed(usuario, senha_digitada):
    if usuario and usuario.senha == senha_digitada:
        usuario.senha = generate_password_hash(senha_digitada)
        db.session.commit()


def notify_success(message):
    flash(message, "success")


def notify_error(message):
    flash(message, "error")


def notify_warning(message):
    flash(message, "warning")


def success_create(item):
    notify_success(f"{item} cadastrado com sucesso.")


def success_update(item):
    notify_success(f"{item} atualizado com sucesso.")


def success_delete(item):
    notify_success(f"{item} removido com sucesso.")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not get_logged_user():
            notify_warning("Faça login para continuar.")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def role_required(required_role):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            usuario = get_logged_user()
            if not usuario:
                notify_warning("Faça login para continuar.")
                return redirect(url_for("login"))
            if usuario.role != required_role:
                notify_error("Você não tem permissão para acessar essa página.")
                return redirect(url_for("public_calendar"))
            return view(*args, **kwargs)

        return wrapped

    return decorator


def migrate_database():
    inspector = inspect(db.engine)
    table_names = set(inspector.get_table_names())

    if "usuario" not in table_names:
        return

    user_columns = {col["name"] for col in inspector.get_columns("usuario")}
    if "role" not in user_columns:
        db.session.execute(
            text("ALTER TABLE usuario ADD COLUMN role VARCHAR(20) DEFAULT 'professor'")
        )
        db.session.commit()

    db.session.execute(
        text(
            "UPDATE usuario SET role = 'professor' "
            "WHERE role IS NULL OR TRIM(role) = ''"
        )
    )
    db.session.commit()


def ensure_default_tecnico():
    tecnico = Usuario.query.filter_by(role=ROLE_TECNICO).first()
    if tecnico:
        return

    admin = Usuario(
        nome="Técnico de Laboratório",
        email="tecnico@kaliana.local",
        senha=generate_password_hash("admin123"),
        role=ROLE_TECNICO,
    )
    db.session.add(admin)
    db.session.commit()


def get_or_create_agenda_config():
    config = ConfiguracaoAgenda.query.order_by(ConfiguracaoAgenda.id.asc()).first()
    if config:
        return config

    config = ConfiguracaoAgenda(
        sabado_fechado=False,
        sabado_somente_manha=True,
        domingo_fechado=True,
    )
    db.session.add(config)
    db.session.commit()
    return config


def get_holidays_between(start_date=None, end_date=None):
    query = Feriado.query.order_by(Feriado.data.asc())
    if start_date and end_date:
        query = query.filter(Feriado.data >= start_date, Feriado.data <= end_date)
    return query.all()


def get_slot_block_reason(day_value, turno, agenda_config, feriados_por_data):
    feriado_descricao = feriados_por_data.get(day_value)
    if feriado_descricao:
        return f"Feriado: {feriado_descricao}"

    weekday = day_value.weekday()

    if weekday == 6 and agenda_config.domingo_fechado:
        return "Domingo indisponível"

    if weekday == 5:
        if agenda_config.sabado_fechado:
            return "Sábado indisponível"
        if agenda_config.sabado_somente_manha and turno != "manha":
            return "Sábado: somente manhã"

    return None


def build_slot(reserva, bloqueio=None):
    if bloqueio:
        return {"status": "indisponivel", "title": "Indisponível", "detail": bloqueio}

    if not reserva:
        return {"status": "livre", "title": "Livre", "detail": ""}

    professor_nome = reserva.professor.nome if reserva.professor else "Professor"

    if reserva.status == "aprovada":
        return {
            "status": "aprovada",
            "title": "Reservado",
            "detail": f"Aula com {professor_nome}",
        }

    return {
        "status": "pendente",
        "title": "Solicitado",
        "detail": f"Solicitação de {professor_nome}",
    }


def build_calendar(week_start, agenda_config):
    week_days = [week_start + timedelta(days=i) for i in range(7)]
    labs = Laboratorio.query.order_by(Laboratorio.nome.asc()).all()
    feriados_semana = get_holidays_between(week_days[0], week_days[-1])
    feriados_por_data = {feriado.data: feriado.descricao for feriado in feriados_semana}

    if not labs:
        return week_days, [], feriados_semana

    reservas = (
        Reserva.query.filter(
            Reserva.data >= week_days[0],
            Reserva.data <= week_days[-1],
            Reserva.status.in_(["pendente", "aprovada"]),
        )
        .order_by(Reserva.created_at.asc())
        .all()
    )

    reservas_por_slot = {}
    for reserva in reservas:
        key = (reserva.laboratorio_id, reserva.data, reserva.turno)
        atual = reservas_por_slot.get(key)
        if not atual or (atual.status == "pendente" and reserva.status == "aprovada"):
            reservas_por_slot[key] = reserva

    rows = []
    for lab in labs:
        for turno_key, turno_label in TURNOS:
            slots = []
            for day in week_days:
                bloqueio = get_slot_block_reason(day, turno_key, agenda_config, feriados_por_data)
                slots.append(
                    build_slot(
                        reservas_por_slot.get((lab.id, day, turno_key)),
                        bloqueio=bloqueio,
                    )
                )

            rows.append(
                {
                    "laboratorio_nome": lab.nome,
                    "turno_key": turno_key,
                    "turno_label": turno_label,
                    "slots": slots,
                }
            )

    return week_days, rows, feriados_semana


def get_admin_stats():
    week_start = get_week_start()
    week_end = week_start + timedelta(days=6)
    agenda_config = get_or_create_agenda_config()

    total_regras_ativas = sum(
        [
            1 if agenda_config.sabado_fechado else 0,
            1 if agenda_config.sabado_somente_manha else 0,
            1 if agenda_config.domingo_fechado else 0,
        ]
    )

    return {
        "total_laboratorios": Laboratorio.query.count(),
        "total_professores": Usuario.query.filter_by(role=ROLE_PROFESSOR).count(),
        "total_pendentes": Reserva.query.filter_by(status="pendente").count(),
        "agendamentos_semana": Reserva.query.filter(
            Reserva.data >= week_start,
            Reserva.data <= week_end,
            Reserva.status.in_(["pendente", "aprovada"]),
        ).count(),
        "total_feriados": Feriado.query.count(),
        "total_regras_ativas": total_regras_ativas,
    }


@app.context_processor
def inject_user_context():
    return {
        "usuario_logado": get_logged_user(),
        "ROLE_TECNICO": ROLE_TECNICO,
        "ROLE_PROFESSOR": ROLE_PROFESSOR,
        "status_labels": STATUS_LABELS,
        "turno_labels": dict(TURNOS),
    }


with app.app_context():
    db.create_all()
    migrate_database()
    ensure_default_tecnico()
    get_or_create_agenda_config()


@app.route("/")
def public_calendar():
    week_start = get_week_start(request.args.get("week"))
    agenda_config = get_or_create_agenda_config()
    week_days, calendar_rows, feriados_semana = build_calendar(week_start, agenda_config)

    return render_template(
        "public_calendar.html",
        week_days=week_days,
        calendar_rows=calendar_rows,
        feriados_semana=feriados_semana,
        agenda_config=agenda_config,
        week_start=week_start,
        week_prev=(week_start - timedelta(days=7)).isoformat(),
        week_next=(week_start + timedelta(days=7)).isoformat(),
    )


@app.route("/home")
def home():
    if get_logged_user():
        return redirect(url_for("dashboard"))
    return redirect(url_for("public_calendar"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if get_logged_user():
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")
        usuario = Usuario.query.filter(func.lower(Usuario.email) == email).first()

        if usuario and is_password_valid(usuario, senha):
            upgrade_legacy_password_if_needed(usuario, senha)
            session.clear()
            session["usuario_id"] = usuario.id
            session["usuario_nome"] = usuario.nome
            session["usuario_role"] = usuario.role
            notify_success(f"Bem-vindo, {usuario.nome}.")
            return redirect(url_for("dashboard"))

        notify_error("Email ou senha inválidos.")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    usuario = get_logged_user()
    if not usuario:
        notify_error("O cadastro de professor é feito apenas pelo técnico.")
        return redirect(url_for("login"))

    if usuario.role != ROLE_TECNICO:
        notify_error("Somente o técnico pode cadastrar professor.")
        return redirect(url_for("dashboard"))

    return redirect(url_for("admin_professores"))


@app.route("/logout")
def logout():
    session.clear()
    notify_success("Sessão encerrada com sucesso.")
    return redirect(url_for("public_calendar"))


@app.route("/dashboard")
@login_required
def dashboard():
    usuario = get_logged_user()
    if usuario.role == ROLE_TECNICO:
        return redirect(url_for("admin_dashboard"))
    return redirect(url_for("professor_dashboard"))


# ADMIN
@app.route("/admin")
@role_required(ROLE_TECNICO)
def admin_dashboard():
    stats = get_admin_stats()
    week_start = get_week_start(request.args.get("week"))
    agenda_config = get_or_create_agenda_config()
    week_days, calendar_rows, feriados_semana = build_calendar(week_start, agenda_config)

    return render_template(
        "admin_dashboard.html",
        week_days=week_days,
        calendar_rows=calendar_rows,
        feriados_semana=feriados_semana,
        agenda_config=agenda_config,
        week_start=week_start,
        week_prev=(week_start - timedelta(days=7)).isoformat(),
        week_next=(week_start + timedelta(days=7)).isoformat(),
        **stats,
    )


@app.route("/admin/laboratorios")
@role_required(ROLE_TECNICO)
def admin_laboratorios():
    laboratorios = Laboratorio.query.order_by(Laboratorio.nome.asc()).all()
    return render_template(
        "admin_laboratorios.html",
        laboratorios=laboratorios,
        total_laboratorios=len(laboratorios),
    )


@app.post("/admin/laboratorios")
@role_required(ROLE_TECNICO)
def create_laboratorio():
    nome = request.form.get("nome", "").strip()
    descricao = request.form.get("descricao", "").strip()

    if not nome:
        notify_error("Informe o nome do laboratório.")
        return redirect(url_for("admin_laboratorios"))

    existe = Laboratorio.query.filter(func.lower(Laboratorio.nome) == nome.lower()).first()
    if existe:
        notify_warning("Já existe um laboratório com esse nome.")
        return redirect(url_for("admin_laboratorios"))

    db.session.add(Laboratorio(nome=nome, descricao=descricao or None))
    db.session.commit()
    success_create("Laboratório")
    return redirect(url_for("admin_laboratorios"))


@app.post("/admin/laboratorios/<int:laboratorio_id>/update")
@role_required(ROLE_TECNICO)
def update_laboratorio(laboratorio_id):
    laboratorio = db.session.get(Laboratorio, laboratorio_id)
    if not laboratorio:
        notify_error("Laboratório não encontrado.")
        return redirect(url_for("admin_laboratorios"))

    nome = request.form.get("nome", "").strip()
    descricao = request.form.get("descricao", "").strip()

    if not nome:
        notify_error("Informe o nome do laboratório.")
        return redirect(url_for("admin_laboratorios"))

    existe = Laboratorio.query.filter(
        func.lower(Laboratorio.nome) == nome.lower(),
        Laboratorio.id != laboratorio.id,
    ).first()

    if existe:
        notify_warning("Já existe um laboratório com esse nome.")
        return redirect(url_for("admin_laboratorios"))

    laboratorio.nome = nome
    laboratorio.descricao = descricao or None
    db.session.commit()
    success_update("Laboratório")
    return redirect(url_for("admin_laboratorios"))


@app.post("/admin/laboratorios/<int:laboratorio_id>/delete")
@role_required(ROLE_TECNICO)
def delete_laboratorio(laboratorio_id):
    laboratorio = db.session.get(Laboratorio, laboratorio_id)
    if not laboratorio:
        notify_error("Laboratório não encontrado.")
        return redirect(url_for("admin_laboratorios"))

    nome_lab = laboratorio.nome
    reservas_removidas = Reserva.query.filter_by(laboratorio_id=laboratorio.id).delete(
        synchronize_session=False
    )
    db.session.delete(laboratorio)
    db.session.commit()

    if reservas_removidas:
        notify_warning(
            f"Laboratório {nome_lab} removido. {reservas_removidas} reserva(s) associada(s) também foram excluídas."
        )
    else:
        success_delete(f"Laboratório {nome_lab}")

    return redirect(url_for("admin_laboratorios"))


@app.route("/admin/professores")
@role_required(ROLE_TECNICO)
def admin_professores():
    professores = (
        Usuario.query.filter_by(role=ROLE_PROFESSOR)
        .order_by(Usuario.nome.asc())
        .all()
    )
    return render_template(
        "admin_professores.html",
        professores=professores,
        total_professores=len(professores),
    )


@app.post("/admin/professores")
@role_required(ROLE_TECNICO)
def create_professor():
    nome = request.form.get("nome", "").strip()
    email = request.form.get("email", "").strip().lower()
    senha = request.form.get("senha", "")

    if not nome or not email or not senha:
        notify_error("Preencha nome, email e senha do professor.")
        return redirect(url_for("admin_professores"))

    if Usuario.query.filter(func.lower(Usuario.email) == email).first():
        notify_warning("Já existe um usuário com esse email.")
        return redirect(url_for("admin_professores"))

    professor = Usuario(
        nome=nome,
        email=email,
        senha=generate_password_hash(senha),
        role=ROLE_PROFESSOR,
    )
    db.session.add(professor)
    db.session.commit()
    success_create("Professor")
    return redirect(url_for("admin_professores"))


@app.post("/admin/professores/<int:professor_id>/update")
@role_required(ROLE_TECNICO)
def update_professor(professor_id):
    professor = Usuario.query.filter_by(id=professor_id, role=ROLE_PROFESSOR).first()
    if not professor:
        notify_error("Professor não encontrado.")
        return redirect(url_for("admin_professores"))

    nome = request.form.get("nome", "").strip()
    email = request.form.get("email", "").strip().lower()
    senha_nova = request.form.get("senha", "")

    if not nome or not email:
        notify_error("Preencha nome e email do professor.")
        return redirect(url_for("admin_professores"))

    email_em_uso = Usuario.query.filter(
        func.lower(Usuario.email) == email,
        Usuario.id != professor.id,
    ).first()

    if email_em_uso:
        notify_warning("Já existe um usuário com esse email.")
        return redirect(url_for("admin_professores"))

    professor.nome = nome
    professor.email = email

    if senha_nova:
        professor.senha = generate_password_hash(senha_nova)

    db.session.commit()
    success_update("Professor")
    return redirect(url_for("admin_professores"))


@app.post("/admin/professores/<int:professor_id>/delete")
@role_required(ROLE_TECNICO)
def delete_professor(professor_id):
    professor = Usuario.query.filter_by(id=professor_id, role=ROLE_PROFESSOR).first()
    if not professor:
        notify_error("Professor não encontrado.")
        return redirect(url_for("admin_professores"))

    nome_professor = professor.nome
    reservas_removidas = Reserva.query.filter_by(professor_id=professor.id).delete(
        synchronize_session=False
    )
    db.session.delete(professor)
    db.session.commit()

    if reservas_removidas:
        notify_warning(
            f"Professor {nome_professor} removido. {reservas_removidas} reserva(s) associada(s) também foram excluídas."
        )
    else:
        success_delete(f"Professor {nome_professor}")
    return redirect(url_for("admin_professores"))


@app.route("/admin/agendamentos")
@role_required(ROLE_TECNICO)
def admin_agendamentos():
    week_start = get_week_start(request.args.get("week"))
    agenda_config = get_or_create_agenda_config()
    week_days, calendar_rows, feriados_semana = build_calendar(week_start, agenda_config)

    recentes = (
        Reserva.query.order_by(Reserva.data.desc(), Reserva.created_at.desc())
        .limit(30)
        .all()
    )

    return render_template(
        "admin_agendamentos.html",
        week_days=week_days,
        calendar_rows=calendar_rows,
        feriados_semana=feriados_semana,
        agenda_config=agenda_config,
        week_start=week_start,
        week_prev=(week_start - timedelta(days=7)).isoformat(),
        week_next=(week_start + timedelta(days=7)).isoformat(),
        recentes=recentes,
    )


@app.route("/admin/pendentes")
@role_required(ROLE_TECNICO)
def admin_pendentes():
    pendentes = (
        Reserva.query.filter_by(status="pendente")
        .order_by(Reserva.data.asc(), Reserva.turno.asc(), Reserva.created_at.asc())
        .all()
    )
    return render_template(
        "admin_pendentes.html",
        pendentes=pendentes,
        total_pendentes=len(pendentes),
    )


@app.post("/admin/reservas/<int:reserva_id>/status")
@role_required(ROLE_TECNICO)
def update_reserva_status(reserva_id):
    acao = request.form.get("acao", "").strip()
    reserva = db.session.get(Reserva, reserva_id)

    if not reserva:
        notify_error("Reserva não encontrada.")
        return redirect(url_for("admin_pendentes"))

    if reserva.status != "pendente":
        notify_warning("Essa reserva já foi avaliada.")
        return redirect(url_for("admin_pendentes"))

    if acao == "aprovar":
        agenda_config = get_or_create_agenda_config()
        feriado = Feriado.query.filter_by(data=reserva.data).first()
        feriados_por_data = {reserva.data: feriado.descricao} if feriado else {}
        bloqueio = get_slot_block_reason(
            reserva.data,
            reserva.turno,
            agenda_config,
            feriados_por_data,
        )

        if bloqueio:
            notify_error(f"Não foi possível aprovar a reserva: {bloqueio}.")
            return redirect(url_for("admin_pendentes"))

        conflito = Reserva.query.filter(
            Reserva.id != reserva.id,
            Reserva.laboratorio_id == reserva.laboratorio_id,
            Reserva.data == reserva.data,
            Reserva.turno == reserva.turno,
            Reserva.status == "aprovada",
        ).first()

        if conflito:
            notify_error("Já existe uma reserva aprovada nesse horário.")
            return redirect(url_for("admin_pendentes"))

        reserva.status = "aprovada"
        db.session.commit()
        notify_success("Reserva aprovada com sucesso.")
        return redirect(url_for("admin_pendentes"))

    if acao == "recusar":
        reserva.status = "recusada"
        db.session.commit()
        notify_warning("Reserva recusada.")
        return redirect(url_for("admin_pendentes"))

    notify_error("Ação inválida.")
    return redirect(url_for("admin_pendentes"))


@app.route("/admin/feriados")
@role_required(ROLE_TECNICO)
def admin_feriados():
    feriados = get_holidays_between()
    return render_template("admin_feriados.html", feriados=feriados)


@app.post("/admin/feriados")
@role_required(ROLE_TECNICO)
def create_feriado():
    data_feriado = parse_date(request.form.get("data"))
    descricao = request.form.get("descricao", "").strip()

    if not data_feriado:
        notify_error("Informe uma data válida para o feriado.")
        return redirect(url_for("admin_feriados"))

    if not descricao:
        notify_error("Informe a descrição do feriado.")
        return redirect(url_for("admin_feriados"))

    existe = Feriado.query.filter_by(data=data_feriado).first()
    if existe:
        notify_warning("Já existe um feriado cadastrado nessa data.")
        return redirect(url_for("admin_feriados"))

    db.session.add(Feriado(data=data_feriado, descricao=descricao))
    db.session.commit()
    success_create("Feriado")
    return redirect(url_for("admin_feriados"))

@app.post("/admin/feriados/<int:feriado_id>/update")
@role_required(ROLE_TECNICO)
def update_feriado(feriado_id):
    feriado = db.session.get(Feriado, feriado_id)
    if not feriado:
        notify_error("Feriado não encontrado.")
        return redirect(url_for("admin_feriados"))

    nova_data = parse_date(request.form.get("data"))
    nova_descricao = request.form.get("descricao", "").strip()

    if not nova_data:
        notify_error("Informe uma data válida para o feriado.")
        return redirect(url_for("admin_feriados"))

    if not nova_descricao:
        notify_error("Informe a descrição do feriado.")
        return redirect(url_for("admin_feriados"))

    existe = Feriado.query.filter(
        Feriado.data == nova_data,
        Feriado.id != feriado.id
    ).first()

    if existe:
        notify_warning("Já existe um feriado cadastrado nessa data.")
        return redirect(url_for("admin_feriados"))

    feriado.data = nova_data
    feriado.descricao = nova_descricao
    db.session.commit()
    success_update("Feriado")
    return redirect(url_for("admin_feriados"))

@app.post("/admin/feriados/<int:feriado_id>/delete")
@role_required(ROLE_TECNICO)
def delete_feriado(feriado_id):
    feriado = db.session.get(Feriado, feriado_id)
    if not feriado:
        notify_error("Feriado não encontrado.")
        return redirect(url_for("admin_feriados"))

    db.session.delete(feriado)
    db.session.commit()
    success_delete("Feriado")
    return redirect(url_for("admin_feriados"))


@app.route("/admin/configuracoes")
@role_required(ROLE_TECNICO)
def admin_configuracoes():
    agenda_config = get_or_create_agenda_config()
    return render_template("admin_configuracoes.html", agenda_config=agenda_config)


@app.post("/admin/configuracao-agenda")
@role_required(ROLE_TECNICO)
def update_agenda_config():
    agenda_config = get_or_create_agenda_config()

    agenda_config.sabado_fechado = request.form.get("sabado_fechado") == "on"
    agenda_config.sabado_somente_manha = request.form.get("sabado_somente_manha") == "on"
    agenda_config.domingo_fechado = request.form.get("domingo_fechado") == "on"

    if agenda_config.sabado_fechado:
        agenda_config.sabado_somente_manha = False

    db.session.commit()
    success_update("Configuração da agenda")
    return redirect(url_for("admin_configuracoes"))


# PROFESSOR
@app.route("/professor")
@role_required(ROLE_PROFESSOR)
def professor_dashboard():
    week_start = get_week_start(request.args.get("week"))
    agenda_config = get_or_create_agenda_config()
    week_days, calendar_rows, feriados_semana = build_calendar(week_start, agenda_config)
    laboratorios = Laboratorio.query.order_by(Laboratorio.nome.asc()).all()
    minhas_reservas = (
        Reserva.query.filter_by(professor_id=get_logged_user().id)
        .order_by(Reserva.data.desc(), Reserva.created_at.desc())
        .all()
    )

    return render_template(
        "professor_dashboard.html",
        laboratorios=laboratorios,
        minhas_reservas=minhas_reservas,
        feriados_semana=feriados_semana,
        week_days=week_days,
        calendar_rows=calendar_rows,
        agenda_config=agenda_config,
        week_start=week_start,
        week_prev=(week_start - timedelta(days=7)).isoformat(),
        week_next=(week_start + timedelta(days=7)).isoformat(),
    )


@app.route("/professor/solicitar")
@role_required(ROLE_PROFESSOR)
def professor_solicitar():
    laboratorios = Laboratorio.query.order_by(Laboratorio.nome.asc()).all()
    return render_template(
        "professor_solicitar.html",
        laboratorios=laboratorios,
        turnos=TURNOS,
        min_date=date.today().isoformat(),
    )


@app.route("/professor/minhas-reservas")
@role_required(ROLE_PROFESSOR)
def professor_minhas_reservas():
    usuario = get_logged_user()
    minhas_reservas = (
        Reserva.query.filter_by(professor_id=usuario.id)
        .order_by(Reserva.data.desc(), Reserva.created_at.desc())
        .all()
    )
    return render_template(
        "professor_minhas_reservas.html",
        minhas_reservas=minhas_reservas,
    )


@app.route("/professor/feriados")
@role_required(ROLE_PROFESSOR)
def professor_feriados():
    feriados = get_holidays_between()
    return render_template("professor_feriados.html", feriados=feriados)


@app.post("/professor/reservas")
@role_required(ROLE_PROFESSOR)
def create_reserva():
    usuario = get_logged_user()

    lab_id_raw = request.form.get("laboratorio_id", "").strip()
    turno = request.form.get("turno", "").strip()
    data_reserva = parse_date(request.form.get("data"))
    valid_turnos = {t[0] for t in TURNOS}

    if not lab_id_raw.isdigit():
        notify_error("Laboratório inválido.")
        return redirect(url_for("professor_solicitar"))

    laboratorio = db.session.get(Laboratorio, int(lab_id_raw))
    if not laboratorio:
        notify_error("Laboratório não encontrado.")
        return redirect(url_for("professor_solicitar"))

    if not data_reserva:
        notify_error("Informe uma data válida para a reserva.")
        return redirect(url_for("professor_solicitar"))

    if data_reserva < date.today():
        notify_error("Não é permitido reservar datas no passado.")
        return redirect(url_for("professor_solicitar"))

    if turno not in valid_turnos:
        notify_error("Turno inválido.")
        return redirect(url_for("professor_solicitar"))

    agenda_config = get_or_create_agenda_config()
    feriado = Feriado.query.filter_by(data=data_reserva).first()
    feriados_por_data = {data_reserva: feriado.descricao} if feriado else {}

    bloqueio = get_slot_block_reason(data_reserva, turno, agenda_config, feriados_por_data)
    if bloqueio:
        notify_error(f"Esse horário está indisponível: {bloqueio}.")
        return redirect(url_for("professor_solicitar"))

    slot_ocupado = Reserva.query.filter(
        Reserva.laboratorio_id == laboratorio.id,
        Reserva.data == data_reserva,
        Reserva.turno == turno,
        Reserva.status.in_(["pendente", "aprovada"]),
    ).first()

    if slot_ocupado:
        if slot_ocupado.status == "aprovada":
            notify_error("Esse horário já está reservado.")
        else:
            notify_warning("Esse horário já possui uma solicitação pendente.")
        return redirect(url_for("professor_solicitar"))

    reserva = Reserva(
        laboratorio_id=laboratorio.id,
        professor_id=usuario.id,
        data=data_reserva,
        turno=turno,
        status="pendente",
    )
    db.session.add(reserva)
    db.session.commit()

    notify_success("Solicitação enviada com sucesso para aprovação do técnico.")
    return redirect(url_for("professor_minhas_reservas"))


if __name__ == "__main__":
    app.run(debug=True)