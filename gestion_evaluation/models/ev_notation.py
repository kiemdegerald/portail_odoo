# -*- coding: utf-8 -*-
"""La notation d'une évaluation : une ligne par critère de la grille.

Chaque ligne porte DEUX appréciations, sur le même critère :

* celle de l'AGENT — son auto-évaluation ;
* celle du MANAGER — la note officielle, celle qui compte.

Chacun ne remplit que sa colonne, pendant la phase qui lui revient, et
la publie quand il a terminé : tant qu'elle n'est pas publiée, l'autre
ne la voit pas. La VALEUR du niveau est recopiée au moment de la saisie,
si bien qu'une échelle modifiée plus tard ne réécrit jamais une notation
déjà faite.
"""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.exceptions import UserError

# Champs réservés à chacun : sert aussi bien au verrou d'écriture qu'à
# l'affichage.
CHAMPS_AGENT = ("niveau_agent_id",)
CHAMPS_MANAGER = ("niveau_manager_id", "commentaire")


class EvNotationLigne(models.Model):
    _name = "ev.notation.ligne"
    _description = "Note d'un critère sur une évaluation"
    _order = "sequence, id"

    appraisal_id = fields.Many2one(
        "hr.appraisal", string="Évaluation", required=True,
        ondelete="cascade", index=True)
    critere_id = fields.Many2one(
        "ev.grille.critere", string="Critère", required=True,
        ondelete="restrict")
    theme_id = fields.Many2one(
        "ev.grille.theme", string="Thème",
        related="critere_id.theme_id", store=True)
    bloc_id = fields.Many2one(
        "ev.grille.bloc", string="Bloc",
        related="critere_id.bloc_id", store=True)
    sequence = fields.Integer(string="Ordre")

    # --- Auto-évaluation de l'agent ---
    niveau_agent_id = fields.Many2one(
        "ev.echelle.niveau", string="Auto-évaluation",
        help="Appréciation que l'agent se donne sur ce critère.")
    valeur_agent = fields.Float(
        string="Note (agent)", compute="_compute_valeurs", store=True,
        readonly=True)

    # --- Évaluation du manager : la note officielle ---
    niveau_manager_id = fields.Many2one(
        "ev.echelle.niveau", string="Appréciation du manager",
        help="Niveau retenu par le supérieur hiérarchique. C'est cette "
             "note qui fait foi.")
    valeur_manager = fields.Float(
        string="Note", compute="_compute_valeurs", store=True, readonly=True,
        help="Note du niveau retenu par le manager, figée à la saisie.")
    ecart = fields.Float(
        string="Écart", compute="_compute_valeurs", store=True,
        help="Note du manager moins auto-évaluation. Utile pour préparer "
             "l'entretien : c'est là que le dialogue se joue.")
    commentaire = fields.Char(string="Observation")
    points_max = fields.Float(
        related="critere_id.points_max", string="Points",
        readonly=True, digits=(5, 2))
    mode_notation = fields.Selection(
        related="critere_id.grille_id.mode_notation", readonly=True)

    @api.constrains("valeur_manager", "valeur_agent")
    def _check_points(self):
        """En mode Points, on ne peut pas attribuer plus que le critère ne
        vaut — sinon la note globale sort de son barème sans qu'on le
        voie."""
        for ligne in self:
            if ligne.mode_notation != "points" or not ligne.points_max:
                continue
            for valeur, qui in ((ligne.valeur_manager, _("du responsable")),
                                (ligne.valeur_agent, _("de l'agent"))):
                if valeur < 0 or valeur > ligne.points_max:
                    raise ValidationError(_(
                        "La note %(qui)s pour « %(critere)s » doit se situer "
                        "entre 0 et %(max)s point(s).",
                        qui=qui, critere=ligne.critere_id.name or "",
                        max=("%g" % ligne.points_max)))

    @api.depends("niveau_agent_id", "niveau_manager_id")
    def _compute_valeurs(self):
        for ligne in self:
            ligne.valeur_agent = (
                ligne.niveau_agent_id.valeur if ligne.niveau_agent_id else 0.0)
            ligne.valeur_manager = (
                ligne.niveau_manager_id.valeur
                if ligne.niveau_manager_id else 0.0)
            ligne.ecart = (
                ligne.valeur_manager - ligne.valeur_agent
                if (ligne.niveau_agent_id and ligne.niveau_manager_id)
                else 0.0)

    _sql_constraints = [
        ("critere_unique", "unique(appraisal_id, critere_id)",
         "Ce critère est déjà présent sur cette évaluation."),
    ]

    def name_get(self):
        return [(l.id, l.critere_id.name or "") for l in self]

    # ------------------------------------------------------------------
    # Verrou de saisie
    # ------------------------------------------------------------------
    # Une note est une pièce du dossier d'un agent : elle ne se saisit que
    # par celui à qui elle appartient, pendant la phase qui y donne droit,
    # et plus du tout une fois publiée ou l'évaluation close. Le contrôle
    # est ICI, au niveau du modèle : masquer une colonne dans la vue
    # n'empêcherait ni l'import, ni l'appel RPC direct.
    @api.model
    def _ev_check_saisie(self, appraisals, champs=None):
        # Le contrôle ne se lève QUE sur demande explicite du système
        # (génération des lignes au lancement d'une campagne). Il ne se
        # lève PAS sur sudo() : le portail écrit en sudo — les modèles du
        # circuit lui sont inaccessibles autrement — mais il ne doit pas
        # échapper aux règles pour autant. L'identité reste celle de
        # l'utilisateur connecté, c'est elle qui décide.
        if self.env.context.get("ev_notation_systeme"):
            return
        champs = set(champs or [])
        for appraisal in appraisals:
            colonne = None
            if champs & set(CHAMPS_AGENT):
                colonne = "agent"
            if champs & set(CHAMPS_MANAGER):
                # Écrire dans les deux colonnes d'un coup n'a pas de sens
                # métier : on refuse plutôt que d'en autoriser une par
                # inadvertance.
                colonne = "mixte" if colonne else "manager"
            motif = appraisal._ev_motif_notation_fermee(colonne=colonne)
            if motif:
                # Le motif se suffit à lui-même : il est rédigé pour être
                # lu. Y accoler le nom de l'opération ORM (« création »,
                # « modification ») n'apprenait rien à personne.
                raise UserError(motif)

    @api.model_create_multi
    def create(self, vals_list):
        champs = set()
        for vals in vals_list:
            champs |= set(vals)
        self._ev_check_saisie(
            self.env["hr.appraisal"].browse([
                v["appraisal_id"] for v in vals_list if v.get("appraisal_id")]),
            champs)
        return super().create(vals_list)

    def write(self, vals):
        self._ev_check_saisie(self.mapped("appraisal_id"), set(vals))
        return super().write(vals)

    def unlink(self):
        self._ev_check_saisie(
            self.mapped("appraisal_id"),
            set(CHAMPS_AGENT) | set(CHAMPS_MANAGER))
        return super().unlink()
