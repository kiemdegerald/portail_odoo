# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class GmMissionMembre(models.Model):
    """Membres d'une mission (cf. tableau « Membres de la mission » de
    l'ordre de mission réel) : chaque membre porte SA photo financière,
    prise à la soumission — sa catégorie détermine son taux journalier.
    Les montants de la mission sont les sommes des membres."""
    _name = "gm.mission.membre"
    _description = "Membre d'une mission"
    _order = "sequence, id"
    # Un chauffeur n'a pas de fiche employé : sans cela, il s'affichait
    # « Sans nom » dans les listes déroulantes (frais, indemnités).
    _rec_name = "nom_affiche"

    mission_id = fields.Many2one(
        "gm.mission", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    # Un missionnaire est SOIT un agent de la banque, SOIT un chauffeur du
    # répertoire. Le chauffeur n'a ni classification ni barème : ses
    # indemnités se saisissent à la main.
    employee_id = fields.Many2one(
        "hr.employee", string="Membre", ondelete="restrict")
    chauffeur_id = fields.Many2one(
        "gm.chauffeur", string="Chauffeur", ondelete="restrict",
        help="Pour un chauffeur du répertoire, qui n'a pas de fiche "
             "employé ni de barème.")
    # DEUX calculs séparés, et c'est volontaire. Réunis dans une seule
    # méthode, le nom restait vide : la fonction étant modifiable, le
    # formulaire l'envoie à l'enregistrement, ce qui neutralise le calcul
    # partagé — et le nom avec. Un membre chauffeur s'affichait alors
    # « Sans nom » dans les listes déroulantes.
    nom_affiche = fields.Char(
        string="Nom", compute="_compute_nom_affiche", store=True)
    job_title = fields.Char(
        string="Fonction", compute="_compute_job_title", store=True,
        readonly=False)
    compte_bancaire = fields.Char(
        string="N° de compte", compute="_compute_compte_bancaire",
        help="Compte crédité par la fiche d'imputation.")

    @api.depends("employee_id", "chauffeur_id",
                 "employee_id.name", "chauffeur_id.name")
    def _compute_nom_affiche(self):
        for membre in self:
            membre.nom_affiche = (membre.employee_id.name
                                  or membre.chauffeur_id.name
                                  or False)

    @api.depends("employee_id", "chauffeur_id")
    def _compute_job_title(self):
        for membre in self:
            membre.job_title = (membre.employee_id.job_title
                                or membre.chauffeur_id.fonction
                                or False)

    @api.depends("employee_id", "chauffeur_id")
    def _compute_compte_bancaire(self):
        for membre in self:
            if membre.employee_id:
                membre.compte_bancaire = membre.employee_id.sudo(
                ).bank_account_id.acc_number or False
            else:
                membre.compte_bancaire =                     membre.chauffeur_id.compte_effectif or False

    @api.constrains("employee_id", "chauffeur_id")
    def _check_identite(self):
        """Un missionnaire, une identité : ni les deux, ni aucune."""
        for membre in self:
            if membre.employee_id and membre.chauffeur_id:
                raise ValidationError(_(
                    "Une ligne désigne soit un agent, soit un chauffeur — "
                    "pas les deux. Videz l'un des deux champs."))
            if not membre.employee_id and not membre.chauffeur_id:
                raise ValidationError(_(
                    "Chaque ligne doit désigner quelqu'un : un agent de la "
                    "banque, ou un chauffeur du répertoire."))
    is_chef = fields.Boolean(
        string="Chef", compute="_compute_is_chef",
        help="Chef de mission = le demandeur de la fiche (ancre du "
             "circuit de validation).")

    @api.depends("employee_id", "mission_id.employee_id")
    def _compute_is_chef(self):
        for membre in self:
            membre.is_chef = (membre.employee_id
                              == membre.mission_id.employee_id)
    currency_id = fields.Many2one(
        # STOCKÉE : au moment d'écrire un champ monétaire, Odoo relit
        # sa devise. Non stockée, elle était relue sur la mission —
        # déjà effacée pendant une suppression en cascade, d'où
        # « Enregistrement inexistant ou supprimé ».
        related="mission_id.currency_id", store=True)

    # --- Photo financière du membre (figée à la soumission) ---
    categorie_agent = fields.Char(
        string="Catégorie", readonly=True, copy=False)
    indemnite_jour = fields.Monetary(
        string="Indemnité / jour", readonly=True, copy=False)
    indemnite_ids = fields.One2many(
        "gm.mission.indemnite", "membre_id", string="Détail des indemnités",
        copy=False,
        help="Une ligne par type d'indemnité, générée à la soumission "
             "depuis le barème.")
    indemnite_total = fields.Monetary(
        string="Indemnité", compute="_compute_indemnite_total", store=True,
        readonly=True, copy=False,
        help="Somme des indemnités du missionnaire, tous types confondus.")

    @api.depends("indemnite_ids.montant")
    def _compute_indemnite_total(self):
        for membre in self:
            membre.indemnite_total = sum(membre.indemnite_ids.mapped("montant"))
    depense_total = fields.Monetary(
        string="Dépensé", compute="_compute_depense_total", store=True,
        readonly=True, copy=False,
        help="Somme de ce que le missionnaire déclare avoir réellement "
             "dépensé, tous types d'indemnité confondus.")
    ecart_total = fields.Monetary(
        string="Écart", compute="_compute_depense_total", store=True,
        readonly=True, copy=False,
        help="Reçu moins dépensé. Positif : il n'a pas tout dépensé.")

    @api.depends("indemnite_ids.montant_depense", "indemnite_total")
    def _compute_depense_total(self):
        for membre in self:
            membre.depense_total = sum(
                membre.indemnite_ids.mapped("montant_depense"))
            membre.ecart_total = (membre.indemnite_total
                                  - membre.depense_total)

    nb_a_justifier = fields.Integer(
        string="Pièces attendues", compute="_compute_nb_a_justifier",
        help="Indemnités à justifier encore incomplètes : montant dépensé "
             "manquant, ou pièce manquante.")

    def _compute_nb_a_justifier(self):
        for membre in self:
            membre.nb_a_justifier = len(membre.indemnite_ids._incompletes())

    frais_ids = fields.One2many(
        "gm.mission.frais", "membre_id", string="Frais du membre")
    autres_frais = fields.Monetary(
        string="Autres frais", compute="_compute_autres_frais", store=True,
        help="Frais PRÉVUS avant le retour, frais RÉELS déclarés à partir "
             "du retour (décompte définitif).")
    total_du = fields.Monetary(
        string="Total dû", compute="_compute_total_du", store=True)
    avance_montant = fields.Monetary(
        string="Avance", copy=False,
        help="Part d'avance du membre, proposée à la soumission "
             "(% paramétrable), ajustable par le gestionnaire jusqu'au "
             "versement.")
    solde = fields.Monetary(
        string="Solde", compute="_compute_total_du", store=True)

    _sql_constraints = [
        ("membre_unique", "unique(mission_id, employee_id)",
         "Cet agent est déjà membre de la mission : il ne peut y figurer "
         "qu'une seule fois."),
    ]

    # `employee_id` est NULL sur une ligne de CHAUFFEUR : la contrainte
    # ci-dessus, qui porte sur lui, laisse donc passer autant de lignes
    # chauffeur qu'on veut — y compris le MÊME chauffeur deux fois, dont
    # les indemnités seraient alors comptées double.
    @api.constrains("mission_id", "chauffeur_id")
    def _check_chauffeur_unique(self):
        for membre in self:
            if membre.chauffeur_id and self.search_count([
                ("id", "!=", membre.id),
                ("mission_id", "=", membre.mission_id.id),
                ("chauffeur_id", "=", membre.chauffeur_id.id),
            ]):
                raise ValidationError(_(
                    "%s figure déjà parmi les missionnaires : il ne peut y "
                    "apparaître qu'une seule fois.",
                    membre.chauffeur_id.name))

    def init(self):
        super().init()
        # Index partiel : le filet, y compris pour un import. Un doublon
        # deja en base ferait echouer sa creation : on trace plutot que de
        # bloquer la mise a jour du module.
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "gm_mission_membre_chauffeur_uniq "
                    "ON gm_mission_membre (mission_id, chauffeur_id) "
                    "WHERE chauffeur_id IS NOT NULL")
        except Exception as exc:
            _logger.warning(
                "Index d'unicite du chauffeur non cree "
                "(doublons existants ?) : %s", exc)

    @api.depends("frais_ids.montant", "frais_ids.type_frais",
                 "mission_id.state")
    def _compute_autres_frais(self):
        for membre in self:
            membre.autres_frais = sum(
                membre.frais_ids.filtered(
                    lambda f: f.type_frais == membre.mission_id._frais_actifs()
                ).mapped("montant"))

    retenue_non_depense = fields.Monetary(
        string="Retenue (non dépensé)", compute="_compute_retenue",
        store=True, readonly=True, copy=False,
        help="Sur les indemnités À JUSTIFIER, la part reçue mais non "
             "dépensée : elle est retenue sur le décompte définitif. "
             "Les indemnités forfaitaires n'entrent pas dans ce calcul — "
             "elles sont acquises à l'agent. Un dépassement n'est pas "
             "remboursé ici : l'indemnité est un plafond, le surcoût se "
             "déclare en « autres frais », pièce à l'appui.")

    @api.depends("indemnite_ids.montant", "indemnite_ids.montant_depense",
                 "indemnite_ids.a_justifier", "mission_id.state")
    def _compute_retenue(self):
        for membre in self:
            # Avant le retour, rien n'est dépensé ni déclaré : retenir
            # quoi que ce soit viderait le décompte sur lequel les
            # valideurs ont statué, et fausserait l'avance.
            if membre.mission_id.state not in ("returned", "closed"):
                membre.retenue_non_depense = 0.0
                continue
            membre.retenue_non_depense = sum(
                max(0.0, (l.montant or 0.0) - (l.montant_depense or 0.0))
                for l in membre.indemnite_ids.filtered("a_justifier"))

    @api.depends("indemnite_total", "autres_frais", "avance_montant",
                 "retenue_non_depense")
    def _compute_total_du(self):
        for membre in self:
            membre.total_du = (membre.indemnite_total + membre.autres_frais
                               - membre.retenue_non_depense)
            membre.solde = membre.total_du - membre.avance_montant

    # ------------------------------------------------------------------
    # Verrou : plus de modification une fois l'avance versée
    # (même règle que les lignes de frais).
    # ------------------------------------------------------------------
    def _check_mission_locked(self, missions):
        # gm_migration : reprise de données ; gm_recompute : recalcul
        # système des indemnités au retour de mission (l'avance est alors
        # déjà versée, mais le décompte définitif doit pouvoir s'écrire).
        # gm_suppression_mission : c'est la mission ENTIÈRE qui est
        # supprimée ; ses lignes partent avec elle, quel que soit son
        # état. Le droit de supprimer la mission a déjà été vérifié.
        if (self.env.context.get("gm_migration")
                or self.env.context.get("gm_recompute")
                or self.env.context.get("gm_suppression_mission")):
            return
        for mission in missions:
            # États terminaux : le décompte est arrêté, plus rien ne bouge —
            # même règle que les lignes de frais (cf. gm_frais.py). Sans ce
            # contrôle, un gestionnaire pouvait encore modifier l'avance d'un
            # membre sur une mission CLÔTURÉE dès lors que « Avance versée »
            # n'était pas cochée, ce qui changeait le solde après clôture.
            if mission.state in ("closed", "cancelled"):
                raise UserError(_(
                    "La mission %s est %s : ses membres et leurs montants ne "
                    "sont plus modifiables.", mission.name,
                    _("clôturée") if mission.state == "closed"
                    else _("annulée")))
            if mission.avance_versee:
                raise UserError(_(
                    "L'avance de la mission %s a déjà été versée : les "
                    "membres ne peuvent plus être modifiés.", mission.name))

    @api.model_create_multi
    def create(self, vals_list):
        missions = self.env["gm.mission"].browse(
            [v["mission_id"] for v in vals_list if v.get("mission_id")])
        self._check_mission_locked(missions)
        # AVANT l'insertion : l'index partiel bloquerait bien le doublon,
        # mais avec un message PostgreSQL brut.
        for vals in vals_list:
            self._refuser_chauffeur_double(vals.get("mission_id"),
                                           vals.get("chauffeur_id"))
        return super().create(vals_list)

    def _refuser_chauffeur_double(self, mission_id, chauffeur_id,
                                  exclure=None):
        if not (mission_id and chauffeur_id):
            return
        domaine = [("mission_id", "=", mission_id),
                   ("chauffeur_id", "=", chauffeur_id)]
        if exclure:
            domaine = [("id", "!=", exclure)] + domaine
        if self.search_count(domaine):
            nom = self.env["gm.chauffeur"].browse(chauffeur_id).name
            raise ValidationError(_(
                "%s figure déjà parmi les missionnaires : il ne peut y "
                "apparaître qu'une seule fois.", nom))

    def write(self, vals):
        # la photo (écrite par la soumission) et la remise à zéro (retour
        # en brouillon) passent par sudo métier avec avance non versée ;
        # ici on ne verrouille que le cas avance déjà décaissée.
        self._check_mission_locked(self.mapped("mission_id"))
        if "chauffeur_id" in vals or "mission_id" in vals:
            for membre in self:
                self._refuser_chauffeur_double(
                    vals.get("mission_id", membre.mission_id.id),
                    vals.get("chauffeur_id", membre.chauffeur_id.id),
                    exclure=membre.id)
        return super().write(vals)

    def unlink(self):
        self._check_mission_locked(self.mapped("mission_id"))
        return super().unlink()

    # --- La déclaration de retour, missionnaire par missionnaire ------
    # Le retour est UNE déclaration pour la mission (tout le monde rentre
    # ensemble), mais chacun répond de SES montants et de SES pièces. Sans
    # état par membre, la RH ne pouvait que tout accepter ou tout renvoyer :
    # un seul agent en faute bloquait ses collègues.
    retour_state = fields.Selection([
        ("a_declarer", "À déclarer"),
        ("declare", "Déclarée"),
        ("valide", "Validée"),
        ("a_corriger", "À corriger"),
    ], string="Déclaration", default="a_declarer", copy=False, required=True,
        help="Où en est la déclaration de retour de CE missionnaire.")
    retour_motif = fields.Text(
        string="Motif du renvoi", readonly=True, copy=False,
        help="Renseigné par la RH quand elle renvoie la déclaration ; "
             "l'agent le lit sur son portail.")
    retour_valide_par_id = fields.Many2one(
        "res.users", string="Validée par", readonly=True, copy=False)
    retour_date_validation = fields.Datetime(
        string="Validée le", readonly=True, copy=False)

    def _marquer_declaree(self):
        """L'agent vient de déposer sa déclaration : elle passe à la RH.

        Une déclaration DÉJÀ validée ne repart pas en arrière — la RH a
        tranché, c'est elle qui rouvrirait le dossier s'il le fallait.
        """
        self.filtered(
            lambda m: m.retour_state in ("a_declarer", "a_corriger")
        ).write({"retour_state": "declare", "retour_motif": False})

    def action_declaration_validee(self):
        """La RH accepte la déclaration de ce missionnaire."""
        for membre in self:
            if membre.retour_state == "valide":
                raise UserError(_(
                    "La déclaration de %s est déjà validée.",
                    membre.nom_affiche or ""))
            if membre.mission_id.state != "returned":
                raise UserError(_(
                    "Le retour de la mission n'est pas encore déclaré : "
                    "il n'y a rien à valider."))
            incompletes = membre.indemnite_ids._incompletes()
            if incompletes:
                raise UserError(_(
                    "%(qui)s n'a pas complété : %(quoi)s.\n\n"
                    "Chaque indemnité à justifier demande le montant "
                    "réellement dépensé ET la pièce. Renvoyez-lui la "
                    "déclaration, ou complétez-la vous-même avant de "
                    "valider.",
                    qui=membre.nom_affiche or "",
                    quoi=", ".join(incompletes.mapped("type_id.name"))))
            membre.write({
                "retour_state": "valide",
                "retour_motif": False,
                "retour_valide_par_id": self.env.uid,
                "retour_date_validation": fields.Datetime.now(),
            })
            membre.mission_id.message_post(body=_(
                "Déclaration de %(qui)s validée par %(par)s.",
                qui=membre.nom_affiche or "", par=self.env.user.name))

    def action_declaration_renvoyee(self, motif=None):
        """La RH renvoie la déclaration à l'agent (motif OBLIGATOIRE)."""
        if not (motif and motif.strip()):
            raise UserError(_("Le motif du renvoi est obligatoire."))
        for membre in self:
            if membre.mission_id.state != "returned":
                raise UserError(_(
                    "Le retour de la mission n'est pas encore déclaré."))
            membre.write({
                "retour_state": "a_corriger",
                "retour_motif": motif.strip(),
                "retour_valide_par_id": False,
                "retour_date_validation": False,
            })
            membre.mission_id.message_post(body=_(
                "Déclaration de %(qui)s renvoyée pour correction par "
                "%(par)s : %(motif)s",
                qui=membre.nom_affiche or "", par=self.env.user.name,
                motif=motif.strip()))

    def action_ouvrir_renvoi(self):
        """Ouvre la fenêtre de motif — le renvoi ne se fait jamais sans."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Renvoyer la déclaration"),
            "res_model": "gm.decision.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_mission_id": self.mission_id.id,
                "default_membre_id": self.id,
                "default_action": "renvoi_declaration",
            },
        }

    def action_imprimer_decompte(self):
        """Le décompte de CE missionnaire seul, pour le service RH.

        C'est exactement le document que l'agent tire depuis son portail :
        même rapport, même gabarit. Seul le point d'entrée est nouveau —
        la RH n'avait aucun moyen de sortir la fiche d'un agent précis
        sans imprimer celle de toute l'équipe.

        Le membre voulu voyage dans le contexte : le client web le
        recopie dans l'URL du rapport, et le contrôleur le réinjecte
        avant le rendu.
        """
        self.ensure_one()
        if self.mission_id.state == "draft":
            raise UserError(_(
                "La mission %s est encore en brouillon : le décompte "
                "n'est arrêté qu'à la soumission.", self.mission_id.name
                or ""))
        return self.env.ref(
            "gestion_mission.action_report_gm_decompte"
        ).with_context(
            gm_decompte_membre_id=self.id
        ).report_action(self.mission_id)
