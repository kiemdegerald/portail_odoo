# -*- coding: utf-8 -*-
"""Soumission du formulaire website « Demande de congés » (/demande-de-conges).

Le formulaire (vue ``website.demande-de-conges``, éditée via le Website
Builder) poste vers ``/website/form/mail.mail`` : Odoo envoie l'email de
notification et cet override crée en plus la demande de congé (``hr.leave``)
de l'employé identifié par son adresse e-mail professionnelle.

Ce comportement était historiquement injecté directement dans le coeur d'Odoo
(``website/controllers/form.py``, méthode ``extract_data``) ; il est déplacé
ici pour que le coeur reste standard. Au passage :

* il ne s'exécute plus que pour le formulaire de congés (l'injection cassait
  tous les autres formulaires website, ex. Contact, par ``KeyError``) ;
* les erreurs renvoient un message clair à l'employé au lieu d'un code champ.
"""
import base64
import logging
from datetime import date, datetime

from odoo import SUPERUSER_ID, _
from odoo.exceptions import ValidationError
from odoo.http import request
from odoo.addons.website.controllers.form import WebsiteForm

from .portal_common import validate_justificatif

_logger = logging.getLogger(__name__)

# Champs personnalisés qui identifient le formulaire « Demande de congés »
# parmi les soumissions génériques ``mail.mail`` du Website Builder.
LEAVE_FORM_FIELDS = ("Type de congé", "Date de début", "Date de fin")

# Formats acceptés pour « Date de début » / « Date de fin »
LEAVE_DATE_FORMATS = ("%d/%m/%Y", "%Y-%m-%d")


class WebsiteFormLeaveRequest(WebsiteForm):

    def _handle_website_form(self, model_name, **kwargs):
        if model_name == "mail.mail" and all(f in kwargs for f in LEAVE_FORM_FIELDS):
            # Crée la demande AVANT l'envoi de l'email de notification :
            # si la demande est invalide, l'email n'est pas envoyé.
            self._portail_create_leave_request(kwargs)
        return super()._handle_website_form(model_name, **kwargs)

    # ------------------------------------------------------------------
    # Création de la demande de congé
    # ------------------------------------------------------------------
    @staticmethod
    def _portail_parse_date(label, value):
        for fmt in LEAVE_DATE_FORMATS:
            try:
                return datetime.strptime((value or "").strip(), fmt).date()
            except ValueError:
                continue
        raise ValidationError(
            _("%s invalide : « %s » (format attendu : JJ/MM/AAAA).", label, value or ""))

    def _portail_create_leave_request(self, values):
        """Crée la demande de congé (état « À approuver ») à partir des champs
        du formulaire. Lève ``ValidationError`` avec un message clair (affiché
        sur la page) si une donnée est invalide.

        Sécurité : réservé aux utilisateurs connectés (la page website est en
        visibilité « connectés », mais la route POST ``/website/form/`` reste
        publique — on revérifie donc ici), et chacun ne peut demander que pour
        lui-même (l'employé résolu par l'email doit être rattaché au compte
        connecté via son contact professionnel).
        """
        user = request.env.user
        if user._is_public():
            raise ValidationError(
                _("Veuillez vous connecter pour envoyer une demande de congé."))

        email = (values.get("email_from") or "").strip()
        employee = request.env["hr.employee"].sudo().search(
            [("work_email", "=ilike", email)], limit=1)
        if not employee:
            raise ValidationError(
                _("Aucun employé ne correspond à l'adresse e-mail « %s ». "
                  "Utilisez votre adresse e-mail professionnelle.", email))
        if employee.work_contact_id != user.partner_id:
            raise ValidationError(
                _("Cette adresse e-mail ne correspond pas à votre compte. "
                  "Utilisez votre propre adresse e-mail professionnelle."))

        contract = request.env["hr.contract"].sudo().search(
            [("employee_id", "=", employee.id)], limit=1)
        if not contract:
            raise ValidationError(
                _("Aucun contrat n'est associé à l'employé %s. "
                  "Contactez le service RH.", employee.name))

        type_name = (values.get("Type de congé") or "").strip()
        # =ilike : correspondance exacte insensible à la casse (évite qu'un
        # nom partiel matche plusieurs types, ex. « Absence déductible » vs
        # « Absence déductible des congés »). Seuls les types cochés
        # « Proposé sur le portail » sont acceptés (le formulaire du site ne
        # propose qu'eux — on revérifie côté serveur).
        leave_type = request.env["hr.leave.type"].sudo().search(
            [("name", "=ilike", type_name), ("portail_published", "=", True)],
            limit=1)
        if not leave_type:
            raise ValidationError(_(
                "Type de congé inconnu ou non proposé sur le portail : "
                "« %s ».", type_name))

        date_from = self._portail_parse_date(_("Date de début"), values.get("Date de début"))
        date_to = self._portail_parse_date(_("Date de fin"), values.get("Date de fin"))
        if date_to < date_from:
            raise ValidationError(
                _("La date de fin ne peut pas précéder la date de début."))
        # Dates passées : refusées, sauf pour les types explicitement
        # autorisés (ex. Congé maladie, régularisé après coup).
        if date_from < date.today() and not leave_type.portail_allow_past_dates:
            raise ValidationError(_(
                "Les dates passées ne sont pas autorisées pour le type "
                "« %s ». Pour une régularisation, contactez le service RH.",
                leave_type.portail_label or leave_type.name))

        # NB 1 : le motif est stocké dans ``private_name`` (champ réel). Écrire
        # ``name`` (champ calculé avec masquage de confidentialité) perdrait
        # silencieusement le texte pour un utilisateur non-officier RH.
        # NB 2 : création en SUPERUSER (pas seulement sudo) : les types en
        # validation automatique (ex. Congé maladie) se valident dès le dépôt,
        # ce qui crée un événement calendrier ``with_user(uid courant)`` —
        # impossible pour un utilisateur portail. Les contrôles métier
        # (connecté + son propre email) sont faits AVANT.
        leave = request.env["hr.leave"].with_user(SUPERUSER_ID).create({
            "employee_id": employee.id,
            "holiday_status_id": leave_type.id,
            "request_date_from": date_from,
            "request_date_to": date_to,
            "private_name": values.get("Description") or values.get("subject") or "",
            "state": "confirm",
        })

        # Comportement historique : mémorise la dernière période demandée sur
        # le contrat (champs Studio), quand ils existent sur cette base.
        contract_vals = {
            field: value
            for field, value in (("x_studio_date_de_dbut", date_from),
                                 ("x_studio_date_de_fin", date_to))
            if field in contract._fields
        }
        if contract_vals:
            contract.write(contract_vals)

        # Justificatif : fichier(s) éventuellement joint(s) au formulaire
        self._portail_attach_justificatifs(leave, values)

        # Prévient le validateur désigné (jamais bloquant : la demande est
        # créée même si l'email échoue).
        leave._portail_notify_validator()

        _logger.info(
            "Portail: demande de congé %s créée depuis le site web "
            "(employé %s, du %s au %s)", leave.id, employee.name, date_from, date_to)
        return leave

    @staticmethod
    def _portail_attach_justificatifs(leave, values):
        """Rattache le(s) fichier(s) du champ « Justificatif » à la demande.

        Le JS du website form indexe le nom des champs fichier à l'envoi
        (« Justificatif[0] », « Justificatif[1] »...) : on matche donc sur le
        nom de base, avant le « [ ».

        Le flux est remis à zéro après lecture pour que le fichier reste
        également joignable à l'email de notification (traitement standard
        du formulaire qui suit).
        """
        files = []
        for key, value in values.items():
            if key.split("[", 1)[0] != "Justificatif":
                continue
            files.extend(value if isinstance(value, list) else [value])
        if not files:
            return
        Attachment = request.env["ir.attachment"].sudo()
        for f in files:
            if not (hasattr(f, "filename") and f.filename):
                continue
            content = f.read()
            try:
                f.stream.seek(0)
            except Exception:
                pass
            # Validation de sécurité : format détecté sur le contenu
            # (PDF/JPEG/PNG) + taille max. Lève ValidationError -> la
            # soumission entière est annulée avec un message clair.
            mimetype = validate_justificatif(f.filename, content or b"")
            Attachment.create({
                "name": f.filename,
                "datas": base64.b64encode(content or b""),
                "mimetype": mimetype,
                "res_model": "hr.leave",
                "res_id": leave.id,
            })
