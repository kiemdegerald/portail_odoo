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
    immatriculation = fields.Char(
        string="Immatriculation",
        help="Immatriculation du véhicule de service, imprimée à la suite "
             "du moyen de déplacement (ex. « Véhicule BF 1666 E3 03 »). "
             "Facultative.")

    @api.onchange("transport")
    def _onchange_transport(self):
        """Une plaque n'a de sens que pour un véhicule de service.

        Sans cela, une plaque saisie puis le transport changé restait en
        base — et s'imprimait sur l'ordre de mission derrière « Avion ».
        """
        if self.transport != "service":
            self.immatriculation = False
    description = fields.Text(
        string="Précisions",
        help="Contexte, participants, programme prévisionnel...")

    state = fields.Selection([
        ("draft", "Brouillon"),
        ("submitted", "Soumise"),
        ("validated", "Validée"),
        ("returned", "Retour déclaré"),
        ("closed", "Clôturée"),
        ("refused", "Refusée"),
        ("cancelled", "Annulée"),
    ], string="Statut", default="draft", required=True, copy=False,
        tracking=True)
    refusal_reason = fields.Text(
        string="Motif du refus", readonly=True, copy=False, tracking=True)
    cancel_reason = fields.Text(
        string="Motif de l'annulation", readonly=True, copy=False,
        tracking=True)

    # --- Retour de mission (note de frais) : réel constaté au retour ---
    date_depart_reelle = fields.Date(
        string="Départ réel", copy=False, tracking=True)
    date_retour_reelle = fields.Date(
        string="Retour réel", copy=False, tracking=True)
    duration_reelle = fields.Integer(
        string="Durée réelle (jours)", compute="_compute_duration_reelle",
        store=True, help="Nombre de jours réellement effectués, bornes "
                         "incluses.")
    retour_commentaire = fields.Text(
        string="Commentaire de retour", copy=False,
        help="Précisions du missionnaire sur le déroulement (retour "
             "anticipé, prolongation, incidents...).")
    # --- Visas de départ et de retour ---------------------------------
    # Le document visé sur place PROUVE que la mission a bien été
    # effectuée aux dates déclarées. L'exigence est photographiée à la
    # soumission : l'activer ensuite n'impose rien aux missions déjà
    # parties, dont personne n'aurait pu faire viser les pièces.
    visa_exige = fields.Boolean(
        string="Visas exigés", readonly=True, copy=False,
        help="Réglage RH photographié à la soumission de cette mission.")
    visa_depart = fields.Binary(
        string="Visa de départ", attachment=True, copy=False,
        help="Document visé au départ / à l'arrivée sur place, portant la "
             "date réelle de départ.")
    visa_depart_filename = fields.Char(
        string="Nom du visa de départ", copy=False)
    visa_retour = fields.Binary(
        string="Visa de retour", attachment=True, copy=False,
        help="Document visé au retour, portant la date réelle de retour.")
    visa_retour_filename = fields.Char(
        string="Nom du visa de retour", copy=False)

    retour_declare_par_id = fields.Many2one(
        "res.users", string="Retour déclaré par", readonly=True, copy=False)
    retour_date_declaration = fields.Datetime(
        string="Date de déclaration du retour", readonly=True, copy=False)
    solde_regle = fields.Boolean(
        string="Solde réglé", copy=False, tracking=True,
        help="À cocher par la finance : complément versé au missionnaire "
             "ou trop-perçu récupéré.")

    # Même relation que `membre_ids`, second point de vue : l'onglet
    # Indemnités liste les MISSIONNAIRES, et le détail poste par poste
    # s'ouvre en cliquant sur l'un d'eux. Un one2many ne pouvant pas
    # figurer deux fois dans la même vue, il en faut deux.
    decompte_ids = fields.One2many(
        "gm.mission.membre", "mission_id",
        string="Décompte par missionnaire", copy=False)

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
    indemnite_ids = fields.One2many(
        "gm.mission.indemnite", "mission_id",
        string="Détail des indemnités", copy=False, readonly=True,
        help="Une ligne par missionnaire et par type d'indemnité, générée "
             "à la soumission depuis le barème.")
    frais_ids = fields.One2many(
        "gm.mission.frais", "mission_id",
        string="Autres frais (à justifier)", copy=False,
        help="Postes de frais complémentaires justifiables (billet, visa, "
             "inscription...) — cf. fiche de décompte. Saisis en brouillon "
             "par le demandeur, ajustables par le gestionnaire jusqu'au "
             "versement de l'avance.")
    # Deux vues filtrées sur le même stock de lignes : le filtre doit
    # être porté par le CHAMP (un `domain` posé sur la vue ne filtre pas
    # l'affichage d'un one2many).
    frais_prevus_ids = fields.One2many(
        "gm.mission.frais", "mission_id", string="Frais prévus",
        domain=[("type_frais", "=", "prevu")], copy=False)
    frais_reels_ids = fields.One2many(
        "gm.mission.frais", "mission_id", string="Frais réels",
        domain=[("type_frais", "=", "reel")], copy=False)
    autres_frais = fields.Monetary(
        string="Total autres frais", copy=False,
        compute="_compute_autres_frais", store=True,
        help="Frais PRÉVUS avant le retour, frais RÉELS déclarés à partir "
             "du retour (décompte définitif).")
    frais_prevus_total = fields.Monetary(
        string="Total frais prévus", copy=False,
        compute="_compute_frais_prevus_total", store=True,
        help="Rappel du prévisionnel, conservé pour la comparaison une "
             "fois les frais réels déclarés.")
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
    can_declare_return = fields.Boolean(
        compute="_compute_can_declare_return",
        help="Déclaration du retour possible ? (mission validée ; le "
             "missionnaire lui-même ou un gestionnaire)")
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

    @api.depends("date_depart_reelle", "date_retour_reelle")
    def _compute_duration_reelle(self):
        for mission in self:
            if mission.date_depart_reelle and mission.date_retour_reelle:
                mission.duration_reelle = (
                    mission.date_retour_reelle
                    - mission.date_depart_reelle).days + 1
            else:
                mission.duration_reelle = 0

    @api.constrains("date_depart", "date_retour")
    def _check_dates(self):
        for mission in self:
            if (mission.date_depart and mission.date_retour
                    and mission.date_retour < mission.date_depart):
                raise ValidationError(_(
                    "La date de retour ne peut pas précéder la date de "
                    "départ."))

    @api.constrains("date_depart_reelle", "date_retour_reelle")
    def _check_dates_reelles(self):
        for mission in self:
            if (mission.date_depart_reelle and mission.date_retour_reelle
                    and mission.date_retour_reelle
                    < mission.date_depart_reelle):
                raise ValidationError(_(
                    "La date de retour réelle ne peut pas précéder la date "
                    "de départ réelle."))

    @api.onchange("membre_ids")
    def _onchange_membre_ids_doublon(self):
        """Tous les agents restent proposés dans la liste ; c'est le
        DOUBLON qui est refusé, immédiatement et avec un message (la
        contrainte d'unicité en base reste le filet de sécurité)."""
        vus, doublons = [], []
        for line in self.membre_ids:
            if not line.employee_id:
                continue
            if line.employee_id.id in vus:
                doublons.append(line.employee_id.name)
                self.membre_ids -= line
            else:
                vus.append(line.employee_id.id)
        if doublons:
            return {"warning": {
                "title": _("Agent déjà membre"),
                "message": _(
                    "%s figure déjà parmi les membres de cette mission : "
                    "un agent ne peut y être inscrit qu'une seule fois.",
                    ", ".join(doublons)),
            }}

    def _frais_actifs(self):
        """Nature des frais qui compte dans le décompte : les PRÉVUS
        jusqu'au départ, les RÉELS à partir du retour déclaré."""
        self.ensure_one()
        return "reel" if self.state in ("returned", "closed") else "prevu"

    @api.depends("frais_ids.montant", "frais_ids.type_frais", "state")
    def _compute_autres_frais(self):
        for mission in self:
            actif = mission._frais_actifs()
            mission.autres_frais = sum(
                mission.frais_ids.filtered(
                    lambda f: f.type_frais == actif).mapped("montant"))

    @api.depends("frais_ids.montant", "frais_ids.type_frais")
    def _compute_frais_prevus_total(self):
        for mission in self:
            mission.frais_prevus_total = sum(
                mission.frais_ids.filtered(
                    lambda f: f.type_frais == "prevu").mapped("montant"))

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

    retenue_non_depense = fields.Monetary(
        string="Retenue (non dépensé)", compute="_compute_retenue",
        store=True, readonly=True, copy=False,
        help="Somme des retenues des missionnaires : ce qui a été reçu "
             "sur une indemnité à justifier mais pas dépensé.")

    @api.depends("membre_ids.retenue_non_depense")
    def _compute_retenue(self):
        for mission in self:
            mission.retenue_non_depense = sum(
                mission.membre_ids.mapped("retenue_non_depense"))

    @api.depends("indemnite_total", "autres_frais", "avance_montant",
                 "retenue_non_depense")
    def _compute_total_du(self):
        for mission in self:
            mission.total_du = (mission.indemnite_total + mission.autres_frais
                                - mission.retenue_non_depense)
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
    def _compute_can_declare_return(self):
        """Le retour se déclare par le CHEF DE MISSION (il répond du
        déroulement pour toute l'équipe) ou par un gestionnaire, qui peut
        saisir à sa place."""
        user_employee = self.env.user.employee_id
        is_manager = self.env.user.has_group(
            "gestion_mission.group_gm_manager")
        for mission in self:
            mission.can_declare_return = (
                mission.state == "validated"
                and (is_manager
                     or (user_employee
                         and user_employee == mission.employee_id)))

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
        Ligne = self.env["gm.mission.indemnite"]
        for membre in self.membre_ids:
            # Un chauffeur du répertoire n'a ni classification ni barème :
            # ses indemnités ont été saisies à la main, on les garde telles
            # quelles et on se contente de calculer son avance.
            if not membre.employee_id:
                total = sum(membre.indemnite_ids.mapped("montant"))
                membre.write({
                    "categorie_agent": False,
                    "indemnite_jour": 0.0,
                    "avance_montant": self.currency_id.round(
                        (total + membre.autres_frais) * pct / 100.0),
                })
                continue
            categorie = self._get_agent_category(membre.employee_id)
            if not categorie:
                raise UserError(_(
                    "Impossible de soumettre : la fiche de %s n'a pas de "
                    "classification (grille salariale), sa catégorie "
                    "d'agent est donc inconnue. Contactez le service RH.",
                    membre.employee_id.name))
            rates = self.env["gm.perdiem.rate"].get_rates(
                self.zone_id, categorie, self.company_id)
            if not rates:
                raise UserError(_(
                    "Aucun barème d'indemnité pour la zone « %(zone)s » et "
                    "la catégorie « %(cat)s » (membre : %(emp)s). Demandez "
                    "au gestionnaire de compléter le barème (Missions > "
                    "Configuration).",
                    zone=self.zone_id.name, cat=categorie,
                    emp=membre.employee_id.name))
            # Une ligne par type d'indemnité : c'est le détail que la
            # banque veut lire poste par poste. La somme reste la même
            # qu'avant si un seul type est configuré.
            membre.indemnite_ids.unlink()
            Ligne.create([{
                "mission_id": self.id,
                "membre_id": membre.id,
                "type_id": rate.type_id.id,
                "sequence": rate.type_id.sequence,
                "jours": self.duration,
                "montant_jour": rate.montant_jour,
                "montant": rate.montant_jour * self.duration,
            } for rate in rates])
            total = sum(r.montant_jour for r in rates) * self.duration
            membre.write({
                "categorie_agent": categorie,
                "indemnite_jour": sum(r.montant_jour for r in rates),
                "avance_montant": self.currency_id.round(
                    (total + membre.autres_frais) * pct / 100.0),
            })
        chef = self.membre_ids.filtered(
            lambda m: m.employee_id == self.employee_id)[:1]
        self.write({
            "categorie_agent": chef.categorie_agent,
            "indemnite_jour": chef.indemnite_jour,
        })

    def unlink(self):
        """Efface la mission APRÈS ses lignes, et dans le bon ordre.

        Sans cela, la suppression échouait sur « Enregistrement inexistant
        ou supprimé » : Odoo effaçait les frais, marquait le total
        « autres frais » du membre à recalculer, puis effaçait le membre —
        et tentait ensuite d'écrire ce total sur une ligne disparue.

        On solde donc les recalculs pendant que les membres existent
        encore, avant de les supprimer à leur tour.
        """
        contexte = self.with_context(gm_suppression_mission=True)
        for mission in contexte:
            mission.indemnite_ids.unlink()
            mission.frais_ids.unlink()
            # Les totaux des membres se recalculent ICI, tant qu'ils sont
            # encore là.
            self.env.flush_all()
            mission.membre_ids.unlink()
            self.env.flush_all()
        return super(GmMission, contexte).unlink()

    def _clear_indemnites(self):
        """Efface la photo financière de tous les membres (retour en
        brouillon : une nouvelle photo sera prise à la re-soumission). Les
        membres et leurs « autres frais » saisis sont conservés."""
        # Le total du membre se recalcule tout seul depuis ses lignes :
        # les effacer suffit à remettre l'indemnité à zéro. On ÉPARGNE
        # celles des chauffeurs : elles ont été saisies à la main, aucun
        # barème ne saurait les régénérer.
        self.membre_ids.indemnite_ids.filtered(
            lambda l: l.membre_id.employee_id).unlink()
        self.membre_ids.write({
            "categorie_agent": False,
            "indemnite_jour": 0,
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
            mission.visa_exige = mission._gm_visa_exige_config()
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
                        m.nom_affiche, m.categorie_agent,
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

    # ------------------------------------------------------------------
    # Retour de mission (note de frais), clôture et annulation
    # ------------------------------------------------------------------
    def _prepare_frais_reels(self):
        """À la déclaration du retour, les frais RÉELS sont pré-remplis
        depuis les PRÉVUS : le missionnaire n'a plus qu'à confirmer,
        corriger les montants et joindre ses justificatifs. Les prévus
        restent intacts à côté (comparaison et piste d'audit)."""
        self.ensure_one()
        if self.frais_ids.filtered(lambda f: f.type_frais == "reel"):
            return
        Frais = self.env["gm.mission.frais"].sudo().with_context(
            gm_recompute=True)
        for prevu in self.frais_ids.filtered(lambda f: f.type_frais == "prevu"):
            Frais.create({
                "mission_id": self.id,
                "membre_id": prevu.membre_id.id,
                "type_frais": "reel",
                "description": prevu.description,
                "montant": prevu.montant,
            })

    def _recompute_indemnites_reelles(self):
        """Recalcule le décompte DÉFINITIF sur la durée réellement
        effectuée, au TAUX FIGÉ AU DÉPART (photo de la soumission) : le
        barème a pu changer entre-temps, le dossier reste jugé sur ses
        propres bases. L'avance déjà versée n'est pas touchée : c'est le
        solde qui absorbe l'écart."""
        self.ensure_one()
        jours = self.duration_reelle or self.duration
        # On recalcule les LIGNES, pas le total du membre : celui-ci en
        # découle. Écrire le total directement laissait les lignes sur
        # l'ancienne durée — la fiche de décompte affichait alors des
        # colonnes qui ne s'additionnaient plus au total.
        lignes = self.indemnite_ids.with_context(gm_recompute=True)
        # Les lignes d'un CHAUFFEUR ont été saisies à la main : aucun
        # barème ne saurait les refaire, on n'y touche pas.
        lignes.filtered(lambda l: l.membre_id.employee_id).write(
            {"jours": jours})
        # On redemande explicitement le total de CHAQUE membre. Sans cela,
        # celui d'un chauffeur — dont aucune ligne n'a bougé — restait sur
        # une valeur périmée, et la fiche affichait un total qui ne
        # correspondait plus à ses colonnes.
        self.membre_ids.modified(["indemnite_ids"])

    @api.model
    def _gm_visa_exige_config(self):
        """La banque exige-t-elle les visas ? Réglage RH (Paramètres >
        Missions). Absent = non exigé : on ne durcit jamais une règle
        dans le dos de l'utilisateur."""
        return self.env["ir.config_parameter"].sudo().get_param(
            "gm.visa_exige", "0") == "1"

    def _check_visas(self):
        """Les deux visas sont-ils déposés ? Uniquement si la mission a
        été soumise alors que la banque les exigeait."""
        for mission in self:
            if not mission.visa_exige:
                continue
            manquants = []
            if not mission.visa_depart:
                manquants.append(_("le visa de départ"))
            if not mission.visa_retour:
                manquants.append(_("le visa de retour"))
            if manquants:
                raise UserError(_(
                    "Le retour ne peut pas être déclaré sans %s. Joignez "
                    "le ou les documents visés sur place (PDF, photo ou "
                    "scan) en regard des dates réelles.",
                    " et ".join(manquants)))

    def action_declare_return(self):
        """Validée -> Retour déclaré : le missionnaire (ou la RH) constate
        les dates réelles ; le décompte définitif est recalculé."""
        for mission in self:
            if mission.state != "validated":
                raise UserError(_(
                    "Seule une mission validée peut faire l'objet d'une "
                    "déclaration de retour."))
            if not (mission.date_depart_reelle and mission.date_retour_reelle):
                raise UserError(_(
                    "Renseignez les dates réelles de départ et de retour."))
            if mission.date_depart_reelle < mission.date_depart:
                raise UserError(_(
                    "Le départ réel (%(reel)s) ne peut pas précéder le "
                    "départ prévu et autorisé (%(prevu)s).",
                    reel=mission.date_depart_reelle.strftime("%d/%m/%Y"),
                    prevu=mission.date_depart.strftime("%d/%m/%Y")))
            today = fields.Date.context_today(mission)
            if mission.date_retour_reelle > today:
                raise UserError(_(
                    "Le retour réel (%s) est dans le futur : déclarez le "
                    "retour une fois la mission effectuée.",
                    mission.date_retour_reelle.strftime("%d/%m/%Y")))
            mission._check_visas()
            mission._check_mes_justificatifs()
            ancien_total = mission.total_du
            mission._prepare_frais_reels()
            mission._recompute_indemnites_reelles()
            mission.write({
                "state": "returned",
                "retour_declare_par_id": self.env.uid,
                "retour_date_declaration": fields.Datetime.now(),
            })
            # Celui qui déclare dépose du même coup SA propre
            # déclaration : ses pièces et ses montants sont déjà saisis.
            mes_employes = mission._gm_employes_utilisateur()
            if mes_employes:
                mission.membre_ids.filtered(
                    lambda m: m.employee_id in mes_employes
                )._marquer_declaree()
            mission.message_post(body=_(
                "Retour déclaré : du %(du)s au %(au)s (%(jours)s jour(s) "
                "réels contre %(prevus)s prévus). Décompte définitif : "
                "%(total)s (était %(ancien)s). Solde : %(solde)s.",
                du=mission.date_depart_reelle.strftime("%d/%m/%Y"),
                au=mission.date_retour_reelle.strftime("%d/%m/%Y"),
                jours=mission.duration_reelle, prevus=mission.duration,
                total=mission.total_du, ancien=ancien_total,
                solde=mission.solde))

    def action_back_to_validated(self):
        """Retour déclaré -> Validée : le gestionnaire renvoie la
        déclaration au missionnaire pour correction."""
        for mission in self:
            if mission.state != "returned":
                raise UserError(_("Cette mission n'est pas au stade du "
                                  "retour déclaré."))
            mission.state = "validated"
            mission.message_post(body=_(
                "Déclaration de retour renvoyée pour correction par %s.",
                self.env.user.name))

    def _gm_employes_utilisateur(self):
        """Les fiches employé de l'utilisateur courant.

        Deux rattachements coexistent : « utilisateur associé » (le lien
        standard) et le contact professionnel (celui que pose le module
        ``portail``). Les deux doivent fonctionner.
        """
        user = self.env.user
        Employee = self.env["hr.employee"].sudo()
        domaine = [("user_id", "=", user.id)]
        if user.partner_id:
            domaine = ["|"] + domaine + [
                ("work_contact_id", "=", user.partner_id.id)]
        return Employee.search(domaine)

    def _check_mes_justificatifs(self):
        """Celui qui déclare le retour fournit d'abord SES pièces.

        Il ne peut rien exiger des autres — chacun dépose les siennes — mais
        il n'a aucune raison de déclarer le retour du groupe en laissant les
        siennes de côté.

        Un gestionnaire RH qui déclare depuis le back-office n'est pas
        missionnaire : il n'a pas de ligne, donc rien ne le bloque.
        """
        self.ensure_one()
        mes_employes = self._gm_employes_utilisateur()
        if not mes_employes:
            return
        manquantes = self.indemnite_ids.filtered(
            lambda l: l.membre_id.employee_id in mes_employes)._incompletes()
        if not manquantes:
            return
        raise UserError(_(
            "Complétez d'abord VOS indemnités à justifier : %s.\n\n"
            "Pour chacune, indiquez le montant réellement dépensé et "
            "joignez la pièce, sur la même page, puis déclarez le retour.",
            ", ".join(manquantes.mapped("type_id.name"))))

    def action_close(self):
        """Retour déclaré -> Clôturée : décompte définitif accepté et
        solde réglé. Plus aucune modification ensuite."""
        for mission in self:
            if mission.state != "returned":
                raise UserError(_(
                    "Seule une mission dont le retour est déclaré peut "
                    "être clôturée."))
            # Les indemnités que la RH a marquées « à justifier » : sans
            # la pièce, la mission ne se clôt pas. On nomme QUI doit quoi —
            # chacun ne fournit que ses propres preuves depuis le portail.
            # Chaque agent répond de SA déclaration : la mission ne se
            # clôt que lorsque la RH les a toutes validées. Un chauffeur
            # du répertoire n'a pas de portail et ne déclare rien — sa
            # ligne n'est pas exigée ici.
            en_attente = mission.membre_ids.filtered(
                lambda m: m.employee_id and m.retour_state != "valide")
            if en_attente:
                raise UserError(_(
                    "Déclarations de retour non validées : %s.\n\n"
                    "Validez chaque missionnaire dans l'onglet Membres "
                    "(ou renvoyez-lui sa déclaration) avant de clôturer.",
                    ", ".join(
                        "%s (%s)" % (m.nom_affiche or "",
                                     dict(m._fields["retour_state"].selection)
                                     .get(m.retour_state, ""))
                        for m in en_attente)))
            indem_sans_piece = mission.indemnite_ids._incompletes()
            if indem_sans_piece:
                manquants = ["%s — %s" % (l.membre_id.nom_affiche or "",
                                          l.type_id.name or "")
                             for l in indem_sans_piece]
                raise UserError(_(
                    "Indemnités à justifier sans pièce jointe :\n%s\n\n"
                    "Chaque missionnaire dépose ses justificatifs depuis "
                    "le portail avant que la mission puisse être clôturée.",
                    "\n".join("• " + m for m in manquants)))
            sans_justif = mission.frais_ids.filtered(
                lambda f: f.type_frais == "reel" and not f.justificatif)
            if sans_justif:
                raise UserError(_(
                    "Frais réels sans justificatif : %s. Joignez les "
                    "pièces (ou supprimez la ligne) avant de clôturer.",
                    ", ".join(sans_justif.mapped("description"))))
            if not mission.currency_id.is_zero(mission.solde) \
                    and not mission.solde_regle:
                raise UserError(_(
                    "Le solde de %(solde)s n'est pas réglé : cochez "
                    "« Solde réglé » une fois le %(sens)s effectué, ou "
                    "corrigez le décompte.",
                    solde=mission.solde,
                    sens=_("versement du complément") if mission.solde > 0
                         else _("recouvrement du trop-perçu")))
            mission.state = "closed"
            mission.message_post(body=_(
                "Mission clôturée par %(user)s. Décompte définitif : "
                "%(total)s, avance %(avance)s, solde %(solde)s.",
                user=self.env.user.name, total=mission.total_du,
                avance=mission.avance_montant, solde=mission.solde))

    def action_cancel(self, reason=None):
        """Annulation d'une mission soumise ou validée (l'événement n'a
        pas eu lieu). Le numéro officiel est CONSERVÉ : une mission
        numérotée ne disparaît jamais (piste d'audit). Si l'avance a été
        versée, le solde indique le montant à récupérer."""
        for mission in self:
            if mission.state not in ("submitted", "validated"):
                raise UserError(_(
                    "Seule une mission soumise ou validée peut être "
                    "annulée."))
            if not (reason and reason.strip()):
                raise UserError(_("Le motif de l'annulation est "
                                  "obligatoire."))
            mission.validation_line_ids.filtered(
                lambda l: l.state in ("waiting", "pending")
            ).sudo().write({"state": "waiting"})
            mission.write({"state": "cancelled", "cancel_reason": reason})
            mission.message_post(body=_(
                "Mission annulée par %(user)s. Motif : %(reason)s%(avance)s",
                user=self.env.user.name, reason=reason,
                avance=(_(" Avance versée de %s à récupérer.",
                          mission.avance_montant)
                        if mission.avance_versee else "")))

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
