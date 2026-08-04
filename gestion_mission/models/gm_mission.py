# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

MISSION_TRANSPORTS = [
    ("service", "Véhicule de service"),
    ("personnel", "Véhicule personnel"),
    ("commun", "Transport en commun"),
    ("avion", "Avion"),
    ("autre", "Autre"),
]


class GmMission(models.Model):
    """Ordre de mission : de la demande à la clôture.

    Cycle de vie (incrément 1) :
        brouillon -> soumise -> validée -> refusée
    La validation passera par le circuit configurable (incrément 2) ; pour
    l'instant une action directe du gestionnaire tient lieu de circuit.
    Le numéro officiel (OM/AAAA/NNNN) n'est attribué qu'à la VALIDATION :
    une demande refusée ne consomme pas de numéro.
    """
    _name = "gm.mission"
    _description = "Ordre de mission"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(
        string="Numéro",
        default=lambda self: _("Brouillon"),
        copy=False, readonly=True, tracking=True,
        help="Numéro officiel de l'ordre de mission (OM/AAAA/NNNN), "
             "attribué automatiquement à la validation.")
    employee_id = fields.Many2one(
        "hr.employee", string="Demandeur", required=True, tracking=True,
        default=lambda self: self.env.user.employee_id,
        help="Collaborateur qui part en mission.")
    department_id = fields.Many2one(
        related="employee_id.department_id", string="Direction / Département",
        store=True)
    job_title = fields.Char(
        related="employee_id.job_title", string="Fonction")
    company_id = fields.Many2one(
        "res.company", string="Société", required=True,
        default=lambda self: self.env.company)

    objet = fields.Char(
        string="Objet de la mission", required=True, tracking=True)
    destination = fields.Char(
        string="Destination", required=True, tracking=True,
        help="Ville (et pays si hors Burkina Faso).")
    zone_id = fields.Many2one(
        "gm.mission.zone", string="Zone", required=True, tracking=True,
        default=lambda self: self.env["gm.mission.zone"].search([], limit=1),
        ondelete="restrict",
        help="Zone du référentiel configurable (Missions > Configuration > "
             "Zones de mission) : détermine le barème d'indemnité "
             "journalière applicable.")
    date_depart = fields.Date(string="Date de départ", tracking=True)
    date_retour = fields.Date(string="Date de retour", tracking=True)
    duration = fields.Integer(
        string="Durée (jours)", compute="_compute_duration", store=True,
        help="Nombre de jours de mission, bornes incluses.")
    transport = fields.Selection(
        MISSION_TRANSPORTS, string="Moyen de transport", default="service")
    description = fields.Text(
        string="Précisions",
        help="Contexte, participants, programme prévisionnel...")

    state = fields.Selection([
        ("draft", "Brouillon"),
        ("submitted", "Soumise"),
        ("validated", "Validée"),
        ("refused", "Refusée"),
    ], string="Statut", default="draft", required=True, copy=False,
        tracking=True)
    refusal_reason = fields.Text(
        string="Motif du refus", readonly=True, copy=False, tracking=True)

    # --- Membres et indemnités (photo par MEMBRE, prise à la soumission) ---
    membre_ids = fields.One2many(
        "gm.mission.membre", "mission_id",
        string="Membres de la mission", copy=False,
        help="Les missionnaires (cf. tableau de l'ordre de mission). Le "
             "demandeur est ajouté automatiquement. Chaque membre a sa "
             "propre indemnité selon sa catégorie.")
    currency_id = fields.Many2one(
        "res.currency", string="Devise",
        related="company_id.currency_id")
    categorie_agent = fields.Char(
        string="Catégorie (chef de mission)", readonly=True, copy=False,
        help="Catégorie du demandeur/chef de mission, figée à la "
             "soumission. Le détail par membre est dans l'onglet Membres.")
    indemnite_jour = fields.Monetary(
        string="Indemnité / jour (chef)", readonly=True, copy=False,
        help="Taux journalier du demandeur/chef de mission. Le détail par "
             "membre est dans l'onglet Membres.")
    indemnite_total = fields.Monetary(
        string="Indemnité de mission", copy=False,
        compute="_compute_indemnite_total", store=True,
        help="Somme des indemnités de tous les membres.")
    frais_ids = fields.One2many(
        "gm.mission.frais", "mission_id",
        string="Autres frais (à justifier)", copy=False,
        help="Postes de frais complémentaires justifiables (billet, visa, "
             "inscription...) — cf. fiche de décompte. Saisis en brouillon "
             "par le demandeur, ajustables par le gestionnaire jusqu'au "
             "versement de l'avance.")
    autres_frais = fields.Monetary(
        string="Total autres frais", copy=False,
        compute="_compute_autres_frais", store=True,
        help="Somme des lignes « Autres frais (à justifier) ».")
    total_du = fields.Monetary(
        string="Total dû", compute="_compute_total_du", store=True,
        help="Indemnité de mission + autres frais.")
    avance_montant = fields.Monetary(
        string="Avance avant départ", copy=False, tracking=True,
        compute="_compute_avance_montant", store=True,
        help="Somme des avances des membres (proposées à la soumission, % "
             "paramétrable ; ajustables par membre par le gestionnaire "
             "jusqu'au versement).")
    avance_versee = fields.Boolean(
        string="Avance versée", copy=False, tracking=True,
        help="À cocher par la finance lors du décaissement (tracé).")
    solde = fields.Monetary(
        string="Solde (dû − avance)", compute="_compute_total_du", store=True,
        help="Positif : reste à payer au retour. Négatif : trop-perçu à "
             "récupérer.")

    # --- Circuit de validation (photo prise à la soumission) ---
    validation_line_ids = fields.One2many(
        "gm.mission.validation", "mission_id",
        string="Circuit de validation", readonly=True, copy=False)
    current_validator_id = fields.Many2one(
        "hr.employee", string="En attente de",
        compute="_compute_current_validator", store=True,
        help="Valideur de l'étape en cours.")
    can_decide = fields.Boolean(
        compute="_compute_can_decide",
        help="L'utilisateur courant peut-il statuer sur l'étape en cours ? "
             "(valideur attendu ou gestionnaire, jamais le demandeur)")
    is_gm_manager = fields.Boolean(
        compute="_compute_is_gm_manager",
        help="L'utilisateur courant est-il gestionnaire des missions ? "
             "(pilote l'éditabilité des montants dans la vue)")
    can_reset = fields.Boolean(
        compute="_compute_can_reset",
        help="Remise en brouillon possible ? Une demande SOUMISE ne peut "
             "être retirée que par son demandeur (les valideurs, eux, "
             "utilisent « Renvoyer pour correction », commentaire à "
             "l'appui). Une demande REFUSÉE peut être retravaillée.")

    # ------------------------------------------------------------------
    # Calculs et contraintes
    # ------------------------------------------------------------------
    @api.depends("date_depart", "date_retour")
    def _compute_duration(self):
        for mission in self:
            if mission.date_depart and mission.date_retour:
                mission.duration = (mission.date_retour - mission.date_depart).days + 1
            else:
                mission.duration = 0

    @api.constrains("date_depart", "date_retour")
    def _check_dates(self):
        for mission in self:
            if (mission.date_depart and mission.date_retour
                    and mission.date_retour < mission.date_depart):
                raise ValidationError(_(
                    "La date de retour ne peut pas précéder la date de "
                    "départ."))

    @api.depends("frais_ids.montant")
    def _compute_autres_frais(self):
        for mission in self:
            mission.autres_frais = sum(mission.frais_ids.mapped("montant"))

    @api.depends("membre_ids.indemnite_total")
    def _compute_indemnite_total(self):
        for mission in self:
            mission.indemnite_total = sum(
                mission.membre_ids.mapped("indemnite_total"))

    @api.depends("membre_ids.avance_montant")
    def _compute_avance_montant(self):
        for mission in self:
            mission.avance_montant = sum(
                mission.membre_ids.mapped("avance_montant"))

    @api.depends("indemnite_total", "autres_frais", "avance_montant")
    def _compute_total_du(self):
        for mission in self:
            mission.total_du = mission.indemnite_total + mission.autres_frais
            mission.solde = mission.total_du - mission.avance_montant

    @api.depends("validation_line_ids.state")
    def _compute_current_validator(self):
        for mission in self:
            pending = mission.validation_line_ids.filtered(
                lambda l: l.state == "pending")[:1]
            mission.current_validator_id = pending.validator_id

    @api.depends_context("uid")
    @api.depends("state", "current_validator_id", "employee_id",
                 "membre_ids.employee_id")
    def _compute_can_decide(self):
        user = self.env.user
        user_employee = user.employee_id
        is_manager = user.has_group("gestion_mission.group_gm_manager")
        for mission in self:
            allowed = (
                mission.state == "submitted"
                and (is_manager
                     or (user_employee
                         and mission.current_validator_id == user_employee))
                # Séparation des tâches : un MEMBRE de la mission ne
                # statue jamais sur celle-ci, même gestionnaire.
                and (not user_employee
                     or user_employee not in (
                         mission.membre_ids.employee_id
                         | mission.employee_id)))
            mission.can_decide = allowed

    @api.depends_context("uid")
    def _compute_is_gm_manager(self):
        is_manager = self.env.user.has_group(
            "gestion_mission.group_gm_manager")
        for mission in self:
            mission.is_gm_manager = is_manager

    @api.depends_context("uid")
    @api.depends("state", "employee_id")
    def _compute_can_reset(self):
        user_employee = self.env.user.employee_id
        for mission in self:
            mission.can_reset = (
                mission.state == "refused"
                or (mission.state == "submitted"
                    and user_employee
                    and user_employee == mission.employee_id))

    @api.model_create_multi
    def create(self, vals_list):
        missions = super().create(vals_list)
        # le demandeur est d'office le premier membre du tableau
        missions._ensure_chef_membre()
        return missions

    # ------------------------------------------------------------------
    # Numérotation
    # ------------------------------------------------------------------
    @api.model
    def _company_sigle(self, company):
        """Sigle de la société pour le numéro d'ordre (ex. « Banque
        Agricole Du Faso » -> BADF, « TEST » -> TEST)."""
        words = [w for w in (company.name or "").split() if w]
        if len(words) > 1:
            return "".join(w[0].upper() for w in words)
        return (words[0].upper() if words else "OM")[:6]

    def _next_om_number(self, company):
        """Prochain numéro d'ordre de mission POUR CETTE SOCIÉTÉ, au format
        officiel de la banque : ``051/2026/BADF`` (numéro sur 3 chiffres /
        année / sigle — cf. ordre de mission réel N°050/2026/BADF).

        Chaque société a sa propre suite continue — pas de trous du point
        de vue d'une entité. Le compteur est créé automatiquement à la
        première mission validée de la société ; les RH peuvent ajuster son
        format (Paramètres > Technique > Séquences).
        """
        Sequence = self.env["ir.sequence"].sudo()
        seq = Sequence.search([
            ("code", "=", "gm.mission"),
            ("company_id", "=", company.id),
        ], limit=1)
        if not seq:
            seq = Sequence.create({
                "name": _("Ordre de mission (%s)", company.name),
                "code": "gm.mission",
                "prefix": "",
                "suffix": "/%%(year)s/%s" % self._company_sigle(company),
                "padding": 3,
                "use_date_range": True,
                "company_id": company.id,
            })
        return seq.next_by_id()

    # ------------------------------------------------------------------
    # Indemnités (photo à la soumission)
    # ------------------------------------------------------------------
    @api.model
    def _get_agent_category(self, employee):
        """Catégorie d'agent d'un employé, lue depuis sa classification
        (grille salariale Studio). Accès défensif : sur une base sans ces
        champs, renvoie False (le message d'erreur guide alors les RH)."""
        employee = employee.sudo()
        classification = getattr(employee, "x_studio_classification", None)
        if classification:
            return getattr(classification, "x_studio_catgorie", False)
        return False

    def _ensure_chef_membre(self):
        """Le demandeur (chef de mission) est TOUJOURS membre : ajouté en
        tête du tableau s'il n'y figure pas."""
        for mission in self:
            if mission.employee_id and mission.employee_id \
                    not in mission.membre_ids.employee_id:
                self.env["gm.mission.membre"].create({
                    "mission_id": mission.id,
                    "employee_id": mission.employee_id.id,
                    "sequence": 1,
                })

    def _ensure_frais_membre(self):
        """Un frais sans missionnaire est rattaché au chef de mission
        (les frais de la fiche de décompte sont PAR missionnaire)."""
        for mission in self:
            orphans = mission.frais_ids.filtered(lambda f: not f.membre_id)
            if orphans:
                chef = mission.membre_ids.filtered(
                    lambda m: m.employee_id == mission.employee_id)[:1]
                orphans.write({"membre_id": chef.id})

    def _avance_pct(self):
        pct_str = self.env["ir.config_parameter"].sudo().get_param(
            "gm.avance_pct", "100")
        try:
            return max(0.0, min(100.0, float(pct_str)))
        except ValueError:
            return 100.0

    def _snapshot_indemnites(self):
        """Fige les montants PAR MEMBRE au moment de la soumission (même
        philosophie que la photo du circuit) : catégorie, taux du barème
        selon la catégorie du membre, indemnité et part d'avance. Les
        valideurs statuent sur des montants qui ne bougeront plus, même si
        le barème est modifié pendant la circulation du dossier."""
        self.ensure_one()
        pct = self._avance_pct()
        for membre in self.membre_ids:
            categorie = self._get_agent_category(membre.employee_id)
            if not categorie:
                raise UserError(_(
                    "Impossible de soumettre : la fiche de %s n'a pas de "
                    "classification (grille salariale), sa catégorie "
                    "d'agent est donc inconnue. Contactez le service RH.",
                    membre.employee_id.name))
            rate = self.env["gm.perdiem.rate"].get_rate(
                self.zone_id, categorie, self.company_id)
            if not rate:
                raise UserError(_(
                    "Aucun barème d'indemnité pour la zone « %(zone)s » et "
                    "la catégorie « %(cat)s » (membre : %(emp)s). Demandez "
                    "au gestionnaire de compléter le barème (Missions > "
                    "Configuration).",
                    zone=self.zone_id.name, cat=categorie,
                    emp=membre.employee_id.name))
            total = rate.montant_jour * self.duration
            membre.write({
                "categorie_agent": categorie,
                "indemnite_jour": rate.montant_jour,
                "indemnite_total": total,
                "avance_montant": self.currency_id.round(
                    (total + membre.autres_frais) * pct / 100.0),
            })
        chef = self.membre_ids.filtered(
            lambda m: m.employee_id == self.employee_id)[:1]
        self.write({
            "categorie_agent": chef.categorie_agent,
            "indemnite_jour": chef.indemnite_jour,
        })

    def _clear_indemnites(self):
        """Efface la photo financière de tous les membres (retour en
        brouillon : une nouvelle photo sera prise à la re-soumission). Les
        membres et leurs « autres frais » saisis sont conservés."""
        self.membre_ids.write({
            "categorie_agent": False,
            "indemnite_jour": 0,
            "indemnite_total": 0,
            "avance_montant": 0,
        })
        self.write({
            "categorie_agent": False,
            "indemnite_jour": 0,
            "avance_versee": False,
        })

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------
    def _create_validation_snapshot(self):
        """PHOTO du circuit configuré, prise à la soumission.

        Les étapes applicables (société de la mission ou communes) sont
        copiées sur la mission avec leur valideur RÉSOLU à cet instant
        (le « supérieur hiérarchique » devient un employé précis). Les
        modifications ultérieures de la configuration n'affectent donc
        jamais une mission déjà en circulation, et la piste d'audit reste
        fidèle à l'époque du dossier.

        Séparation des tâches : une étape qui se résoudrait sur le
        demandeur lui-même est IGNORÉE (tracé au chatter) — personne ne
        se valide soi-même.
        """
        self.ensure_one()
        steps = self.env["gm.validation.step"].search([
            ("company_id", "in", [False, self.company_id.id]),
        ])
        if not steps:
            raise UserError(_(
                "Aucun circuit de validation n'est configuré pour les "
                "missions. Demandez au gestionnaire de définir les niveaux "
                "(Missions > Configuration > Circuit de validation)."))

        lines, skipped = [], []
        for step in steps:
            if step.validator_type == "manager":
                validator = self.employee_id.parent_id
                if not validator:
                    raise UserError(_(
                        "Impossible de soumettre : le niveau « %(step)s » "
                        "attend le supérieur hiérarchique, mais la fiche de "
                        "%(emp)s n'a pas de manager défini.",
                        step=step.name, emp=self.employee_id.name))
            else:
                validator = step.validator_id
            if validator in (self.membre_ids.employee_id | self.employee_id):
                skipped.append(step.name)
                continue
            lines.append({
                "mission_id": self.id,
                "sequence": step.sequence,
                "name": step.name,
                "validator_id": validator.id,
                "state": "waiting",
            })
        if not lines:
            raise UserError(_(
                "Aucun niveau de validation applicable : toutes les étapes "
                "se résolvent sur le demandeur lui-même. Contactez le "
                "gestionnaire."))
        records = self.env["gm.mission.validation"].sudo().create(lines)
        records[0].state = "pending"
        if skipped:
            self.message_post(body=_(
                "Étape(s) ignorée(s) car un membre de la mission ne peut "
                "pas la valider lui-même : %s", ", ".join(skipped)))
        return records

    def _get_current_line(self):
        self.ensure_one()
        return self.validation_line_ids.filtered(
            lambda l: l.state == "pending")[:1]

    def _get_decision_actor(self):
        """Employé qui décide : l'utilisateur courant ou — appel portail
        en sudo — l'employé AUTHENTIFIÉ transmis via le contexte
        ``gm_actor_employee_id`` (accepté uniquement en sudo : le
        contrôleur portail a résolu l'identité depuis la session)."""
        actor_id = self.env.context.get("gm_actor_employee_id")
        if actor_id and self.env.su:
            return self.env["hr.employee"].sudo().browse(actor_id)
        return self.env.user.employee_id

    def _get_decision_actor_name(self):
        """Nom à tracer dans le chatter pour la décision en cours."""
        actor_id = self.env.context.get("gm_actor_employee_id")
        if actor_id and self.env.su:
            return self.env["hr.employee"].sudo().browse(actor_id).name
        return self.env.user.name

    def _check_decision_rights(self):
        """Qui peut statuer sur l'étape en cours : le valideur attendu, ou
        un gestionnaire — mais JAMAIS le demandeur (séparation des tâches,
        exigence de contrôle interne). Via le portail (acteur transmis en
        contexte), pas de passe-droit gestionnaire : seul le valideur
        attendu peut statuer."""
        self.ensure_one()
        user = self.env.user
        portal_actor = bool(
            self.env.context.get("gm_actor_employee_id") and self.env.su)
        user_employee = self._get_decision_actor()
        if user_employee and user_employee in (
                self.membre_ids.employee_id | self.employee_id):
            raise UserError(_(
                "Séparation des tâches : un membre de la mission ne peut "
                "pas statuer sur celle-ci."))
        if not portal_actor \
                and user.has_group("gestion_mission.group_gm_manager"):
            return
        line = self._get_current_line()
        if not (user_employee and line and line.validator_id == user_employee):
            raise UserError(_(
                "Cette étape attend la décision de %s.",
                line.validator_id.name if line else _("personne")))

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------
    def _check_dates_at_submit(self):
        """Contrôles de cohérence des dates, au moment de la soumission :
        - pas de départ dans le passé (une mission s'autorise AVANT de
          partir — « aucun engagement de frais sans validation préalable ») ;
        - pas de chevauchement avec une autre mission soumise ou validée du
          même agent (il ne peut pas être à deux endroits à la fois)."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        if self.date_depart < today:
            raise UserError(_(
                "La date de départ (%(date)s) est déjà passée : une mission "
                "doit être autorisée avant le départ. Corrigez les dates.",
                date=self.date_depart.strftime("%d/%m/%Y")))
        member_emps = self.membre_ids.employee_id | self.employee_id
        overlap = self.search([
            ("id", "!=", self.id),
            ("state", "in", ("submitted", "validated")),
            ("date_depart", "<=", self.date_retour),
            ("date_retour", ">=", self.date_depart),
            "|", ("employee_id", "in", member_emps.ids),
            ("membre_ids.employee_id", "in", member_emps.ids),
        ], limit=1)
        if overlap:
            concerned = ((overlap.membre_ids.employee_id
                          | overlap.employee_id) & member_emps)
            raise UserError(_(
                "%(emp)s participe déjà à une mission « %(objet)s » "
                "(%(num)s) du %(du)s au %(au)s qui chevauche cette période.",
                emp=", ".join(concerned.mapped("name")),
                objet=overlap.objet,
                num=overlap.name if overlap.state == "validated"
                    else _("soumise, en attente de validation"),
                du=overlap.date_depart.strftime("%d/%m/%Y"),
                au=overlap.date_retour.strftime("%d/%m/%Y")))

    def action_submit(self):
        """Brouillon -> Soumise : dossier complet + photo du circuit."""
        for mission in self:
            if mission.state != "draft":
                raise UserError(_("Seule une demande en brouillon peut être "
                                  "soumise."))
            if not (mission.date_depart and mission.date_retour):
                raise UserError(_("Renseignez les dates de départ et de "
                                  "retour avant de soumettre."))
            mission._ensure_chef_membre()
            mission._ensure_frais_membre()
            mission._check_dates_at_submit()
            mission._snapshot_indemnites()
            lines = mission._create_validation_snapshot()
            mission.state = "submitted"
            mission.message_post(body=_(
                "Demande soumise (%(nb)s membre(s)). Circuit : "
                "%(circuit)s. Indemnités : %(detail)s — total %(total)s.",
                nb=len(mission.membre_ids),
                circuit=" → ".join("%s (%s)" % (l.name, l.validator_id.name)
                                   for l in lines),
                detail="; ".join(
                    "%s (%s, %s j × %s = %s)" % (
                        m.employee_id.name, m.categorie_agent,
                        mission.duration, m.indemnite_jour,
                        m.indemnite_total)
                    for m in mission.membre_ids),
                total=mission.indemnite_total))

    def action_approve_step(self, comment=None):
        """Approuve l'étape en cours ; dernière étape -> mission validée."""
        for mission in self:
            if mission.state != "submitted":
                raise UserError(_("Cette demande n'est pas en attente de "
                                  "validation."))
            mission._check_decision_rights()
            line = mission._get_current_line()
            line.sudo().write({
                "state": "approved",
                "acted_by_id": self.env.uid,
                "date_action": fields.Datetime.now(),
                "comment": comment or False,
            })
            mission.message_post(body=_(
                "Niveau « %(step)s » approuvé par %(user)s.%(note)s",
                step=line.name, user=mission._get_decision_actor_name(),
                note=(_(" Commentaire : %s", comment) if comment else "")))
            nxt = mission.validation_line_ids.filtered(
                lambda l: l.state == "waiting")[:1]
            if nxt:
                nxt.sudo().state = "pending"
            else:
                mission._finalize_validation()

    def action_refuse_step(self, comment=None):
        """Refuse la demande à l'étape en cours (motif OBLIGATOIRE)."""
        for mission in self:
            if mission.state != "submitted":
                raise UserError(_("Cette demande n'est pas en attente de "
                                  "validation."))
            mission._check_decision_rights()
            if not (comment and comment.strip()):
                raise UserError(_("Le motif du refus est obligatoire."))
            line = mission._get_current_line()
            line.sudo().write({
                "state": "refused",
                "acted_by_id": self.env.uid,
                "date_action": fields.Datetime.now(),
                "comment": comment,
            })
            mission.write({"state": "refused", "refusal_reason": comment})
            mission.message_post(body=_(
                "Demande refusée au niveau « %(step)s » par %(user)s. "
                "Motif : %(reason)s",
                step=line.name, user=mission._get_decision_actor_name(),
                reason=comment))

    def action_send_back(self, comment=None):
        """Renvoie la demande au demandeur pour correction (commentaire
        OBLIGATOIRE). La photo du circuit est effacée : une nouvelle photo
        sera prise à la re-soumission."""
        for mission in self:
            if mission.state != "submitted":
                raise UserError(_("Cette demande n'est pas en attente de "
                                  "validation."))
            mission._check_decision_rights()
            if not (comment and comment.strip()):
                raise UserError(_("Précisez ce que le demandeur doit "
                                  "corriger."))
            mission.validation_line_ids.sudo().unlink()
            mission._clear_indemnites()
            mission.state = "draft"
            mission.message_post(body=_(
                "Demande renvoyée pour correction par %(user)s : %(reason)s",
                user=mission._get_decision_actor_name(), reason=comment))

    def _finalize_validation(self):
        """Toutes les étapes approuvées -> Validée + numéro officiel."""
        for mission in self:
            mission.write({
                "state": "validated",
                "name": mission._next_om_number(mission.company_id),
            })
            mission.message_post(body=_(
                "Circuit terminé — mission validée, ordre de mission %s.",
                mission.name))

    def action_reset_to_draft(self):
        """Retour en brouillon — deux cas seulement :
        - une demande SOUMISE, retirée par SON DEMANDEUR (les valideurs et
          gestionnaires passent par « Renvoyer pour correction », qui
          exige un commentaire tracé) ;
        - une demande REFUSÉE, retravaillée avant re-soumission.
        Une mission validée ne revient jamais en arrière (piste d'audit)."""
        for mission in self:
            if mission.state not in ("submitted", "refused"):
                raise UserError(_("Seule une demande soumise ou refusée "
                                  "peut revenir en brouillon."))
            if mission.state == "submitted":
                # Le portail agit en sudo : il passe l'employé AUTHENTIFIÉ
                # (résolu depuis la session) via le contexte. La règle,
                # elle, reste ici : seul le demandeur retire sa demande.
                actor_id = self.env.context.get("gm_actor_employee_id")
                if actor_id and self.env.su:
                    user_employee = self.env["hr.employee"].browse(actor_id)
                else:
                    user_employee = self.env.user.employee_id
                if not (user_employee
                        and user_employee == mission.employee_id):
                    raise UserError(_(
                        "Seul le demandeur peut retirer sa demande "
                        "soumise. Pour la lui renvoyer, utilisez "
                        "« Renvoyer pour correction » (avec un "
                        "commentaire)."))
            mission.validation_line_ids.sudo().unlink()
            mission._clear_indemnites()
            mission.write({"state": "draft", "refusal_reason": False})
            mission.message_post(body=_("Demande remise en brouillon."))
