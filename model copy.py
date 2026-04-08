from datetime import datetime

from extensions import db


class Usuario(db.Model):
    __tablename__ = "usuario"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    senha = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="professor")

    reservas = db.relationship("Reserva", back_populates="professor", lazy=True)


class Laboratorio(db.Model):
    __tablename__ = "laboratorio"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), unique=True, nullable=False)
    descricao = db.Column(db.String(255), nullable=True)

    reservas = db.relationship("Reserva", back_populates="laboratorio", lazy=True)


class Reserva(db.Model):
    __tablename__ = "reserva"

    id = db.Column(db.Integer, primary_key=True)
    laboratorio_id = db.Column(db.Integer, db.ForeignKey("laboratorio.id"), nullable=False)
    professor_id = db.Column(db.Integer, db.ForeignKey("usuario.id"), nullable=False)
    data = db.Column(db.Date, nullable=False)
    turno = db.Column(db.String(20), nullable=False)  # manha, tarde, noite
    status = db.Column(db.String(20), nullable=False, default="pendente")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    laboratorio = db.relationship("Laboratorio", back_populates="reservas")
    professor = db.relationship("Usuario", back_populates="reservas")


class ConfiguracaoAgenda(db.Model):
    __tablename__ = "configuracao_agenda"

    id = db.Column(db.Integer, primary_key=True)
    sabado_fechado = db.Column(db.Boolean, nullable=False, default=False)
    sabado_somente_manha = db.Column(db.Boolean, nullable=False, default=True)
    domingo_fechado = db.Column(db.Boolean, nullable=False, default=True)


class Feriado(db.Model):
    __tablename__ = "feriado"

    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Date, unique=True, nullable=False)
    descricao = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
