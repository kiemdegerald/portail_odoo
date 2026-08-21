# -*- coding: utf-8 -*-
"""Sorties Excel de l'évaluation.

Deux besoins distincts, deux classeurs :

* la **fiche d'un agent** — la feuille remplie, à l'image de la fiche papier
  de la banque, à joindre au dossier ou à remettre en entretien ;
* le **récapitulatif d'une campagne** — une ligne par agent, une colonne par
  critère, exploitable tel quel pour un tri, un graphique ou un import.

Le classeur est produit en mémoire par ``xlsxwriter`` (livré avec Odoo) et
remis par un contrôleur : pas de dépendance externe à installer.
"""
import html
import io
import re

from odoo import _, models
from odoo.exceptions import UserError

try:
    import xlsxwriter
except ImportError:  # pragma: no cover - xlsxwriter est fourni avec Odoo
    xlsxwriter = None


# Couleur d'en-tête : le violet Odoo, pour rester dans la charte des autres
# éditions du projet.
_ENTETE = "#714B67"


def _styles(classeur):
    """Jeu de formats commun aux deux classeurs."""
    return {
        "titre": classeur.add_format({
            "bold": True, "font_size": 15, "font_color": _ENTETE}),
        "soustitre": classeur.add_format({
            "font_size": 10, "font_color": "#666666"}),
        "entete": classeur.add_format({
            "bold": True, "font_color": "white", "bg_color": _ENTETE,
            "border": 1, "text_wrap": True, "valign": "vcenter",
            "align": "center"}),
        "libelle": classeur.add_format({"bold": True}),
        "rubrique": classeur.add_format({
            "bold": True, "bg_color": "#F0E6EE", "border": 1}),
        "sous_rubrique": classeur.add_format({
            "bold": True, "bg_color": "#F7F2F6", "border": 1}),
        "critere": classeur.add_format({"border": 1, "text_wrap": True}),
        "texte": classeur.add_format({"border": 1, "text_wrap": True,
                                      "valign": "top"}),
        "nombre": classeur.add_format({
            "border": 1, "num_format": "0.00", "align": "center"}),
        "pourcent": classeur.add_format({
            "border": 1, "num_format": "0.0", "align": "center"}),
        "total": classeur.add_format({
            "bold": True, "border": 1, "num_format": "0.00",
            "bg_color": "#F0E6EE", "align": "center"}),
        "total_libelle": classeur.add_format({
            "bold": True, "border": 1, "bg_color": "#F0E6EE"}),
        "vide": classeur.add_format({"border": 1, "align": "center",
                                     "font_color": "#999999"}),
    }


class EvExport(models.AbstractModel):
    """Fabrique des classeurs. Modèle abstrait : aucune table, mais les
    méthodes restent surchargeables et testables comme n'importe quel
    service Odoo."""
    _name = "ev.export"
    _description = "Éditions Excel de l'évaluation"

    def _check_xlsxwriter(self):
        if xlsxwriter is None:
            raise UserError(_(
                "La bibliothèque xlsxwriter n'est pas disponible sur ce "
                "serveur : l'export Excel ne peut pas être produit."))

    # ------------------------------------------------------------------
    # Fiche d'un agent
    # ------------------------------------------------------------------
    def fiche_evaluation(self, appraisal):
        """Classeur d'une évaluation : la fiche remplie, bloc par bloc,
        avec les moyennes de thèmes et la note globale."""
        self._check_xlsxwriter()
        appraisal.ensure_one()
        flux = io.BytesIO()
        classeur = xlsxwriter.Workbook(flux, {"in_memory": True})
        f = _styles(classeur)
        feuille = classeur.add_worksheet("Fiche d'évaluation")
        feuille.set_column(0, 0, 52)
        feuille.set_column(1, 1, 30)
        feuille.set_column(2, 3, 11)
        feuille.set_column(4, 4, 40)
        feuille.set_landscape()
        feuille.set_paper(9)  # A4
        feuille.fit_to_pages(1, 0)
        feuille.repeat_rows(0, 0)

        employee = appraisal.employee_id
        ligne = 0
        feuille.write(ligne, 0, _("FICHE D'ÉVALUATION"), f["titre"])
        ligne += 2
        for etiquette, valeur in self._entete_fiche(appraisal):
            feuille.write(ligne, 0, etiquette, f["libelle"])
            feuille.write(ligne, 1, valeur or "")
            ligne += 1
        ligne += 1

        for colonne, titre in enumerate([
                _("Bloc / Thème / Critère"), _("Auto-évaluation"),
                _("Appréciation du manager"), _("Note"), _("Observation")]):
            feuille.write(ligne, colonne, titre, f["entete"])
        ligne += 1

        notes = {n.critere_id.id: n for n in appraisal.ev_note_ids}
        valeurs = {cid: n.valeur_manager for cid, n in notes.items()
                   if n.niveau_manager_id}
        valeurs_agent = {cid: n.valeur_agent for cid, n in notes.items()
                         if n.niveau_agent_id}

        def ecrire_regroupement(libelle, score_agent, score, style, retrait):
            nonlocal ligne
            feuille.write(ligne, 0, "%s%s" % ("    " * retrait, libelle or ""),
                          style)
            if score_agent is None:
                feuille.write(ligne, 1, "—", style)
            else:
                feuille.write_number(ligne, 1, round(score_agent, 2), style)
            feuille.write(ligne, 2, "", style)
            if score is None:
                feuille.write(ligne, 3, "—", style)
            else:
                feuille.write_number(ligne, 3, round(score, 2), style)
            feuille.write(ligne, 4, "", style)
            ligne += 1

        def ecrire_critere(critere):
            nonlocal ligne
            note = notes.get(critere.id)
            feuille.write(ligne, 0, "        %s" % (critere.name or ""),
                          f["critere"])
            if note and note.niveau_agent_id:
                feuille.write_number(ligne, 1, note.valeur_agent, f["nombre"])
            else:
                feuille.write(ligne, 1, _("non renseigné"), f["vide"])
            feuille.write(ligne, 2,
                          note.niveau_manager_id.name
                          if note and note.niveau_manager_id else "",
                          f["critere"])
            if note and note.niveau_manager_id:
                feuille.write_number(ligne, 3, note.valeur_manager,
                                     f["nombre"])
            else:
                feuille.write(ligne, 3, _("non noté"), f["vide"])
            feuille.write(ligne, 4, (note.commentaire if note else "") or "",
                          f["texte"])
            ligne += 1

        grille = appraisal.ev_grille_id
        if grille:
            for bloc in grille.bloc_ids:
                ecrire_regroupement(bloc.name, bloc._score(valeurs_agent),
                                    bloc._score(valeurs), f["rubrique"], 0)
                for theme in bloc.theme_ids:
                    ecrire_regroupement(theme.name,
                                        theme._score(valeurs_agent),
                                        theme._score(valeurs),
                                        f["sous_rubrique"], 1)
                    for critere in theme.critere_ids:
                        ecrire_critere(critere)
            globale = grille._score(valeurs)
            globale_agent = grille._score(valeurs_agent)
            feuille.write(ligne, 0, _("NOTE GLOBALE"), f["total_libelle"])
            if globale_agent is None:
                feuille.write(ligne, 1, "—", f["total"])
            else:
                feuille.write_number(ligne, 1, round(globale_agent, 2),
                                     f["total"])
            feuille.write(ligne, 2, "", f["total_libelle"])
            if globale is None:
                feuille.write(ligne, 3, "—", f["total"])
            else:
                feuille.write_number(ligne, 3, round(globale, 2), f["total"])
            feuille.write(ligne, 4, "", f["total_libelle"])
            ligne += 2
            if not appraisal.ev_notation_complete:
                feuille.write(ligne, 0, _(
                    "Notation incomplète : %(faits)s critère(s) notés sur "
                    "%(total)s. La note globale ne porte que sur les critères "
                    "appréciés.",
                    faits=appraisal.ev_nb_notes,
                    total=appraisal.ev_nb_criteres), f["soustitre"])
                ligne += 2
        else:
            feuille.write(ligne, 0, _(
                "Aucune grille n'est posée sur cette évaluation."),
                f["soustitre"])
            ligne += 2

        # Les commentaires de la fiche : le chiffre ne dit pas tout, et le
        # document doit se lire seul, hors d'Odoo.
        for titre, contenu in (
                (_("Commentaires du collaborateur"),
                 appraisal.employee_feedback),
                (_("Commentaires du supérieur hiérarchique"),
                 appraisal.manager_feedback)):
            feuille.write(ligne, 0, titre, f["libelle"])
            ligne += 1
            texte = self._texte_depuis_html(contenu)
            if texte:
                for paragraphe in texte.splitlines():
                    feuille.write(ligne, 0, paragraphe, f["texte"])
                    ligne += 1
            else:
                feuille.write(ligne, 0, _("(non renseigné)"), f["vide"])
                ligne += 1
            ligne += 1

        # Piste d'audit : qui a fait quoi, et quand.
        if appraisal.ev_etape_ids:
            feuille.write(ligne, 0, _("Circuit de validation"), f["libelle"])
            ligne += 1
            for colonne, titre in enumerate([
                    _("Phase"), _("Acteur attendu"), _("Statut"),
                    _("Traitée par"), _("Le")]):
                feuille.write(ligne, colonne, titre, f["entete"])
            ligne += 1
            statuts = dict(
                self.env["ev.evaluation.etape"]._fields["state"].selection)
            for etape in appraisal.ev_etape_ids:
                feuille.write(ligne, 0, etape.name or "", f["critere"])
                feuille.write(ligne, 1,
                              etape.validator_id.name or _("Service RH"),
                              f["critere"])
                feuille.write(ligne, 2,
                              "%s%s" % (statuts.get(etape.state, etape.state),
                                        " — %s" % etape.skip_reason
                                        if etape.skip_reason else ""),
                              f["critere"])
                feuille.write(ligne, 3, etape.acted_by_id.name or "",
                              f["critere"])
                feuille.write(ligne, 4,
                              self._date_locale(etape.date_action),
                              f["critere"])
                ligne += 1

        classeur.close()
        flux.seek(0)
        nom = _("Fiche evaluation - %(agent)s%(campagne)s.xlsx",
                agent=self._nettoyer(employee.name),
                campagne=" - %s" % self._nettoyer(
                    appraisal.ev_campagne_id.name)
                if appraisal.ev_campagne_id else "")
        return nom, flux.read()

    def _entete_fiche(self, appraisal):
        employee = appraisal.employee_id
        etats = dict(self.env["hr.appraisal"]._fields["state"].selection)
        return [
            (_("Agent"), employee.name),
            (_("Poste"), employee.job_title or
             employee.job_id.name or ""),
            (_("Département"), employee.department_id.name or ""),
            (_("Supérieur hiérarchique"), employee.parent_id.name or ""),
            (_("Campagne"), appraisal.ev_campagne_id.name or _("Hors campagne")),
            (_("Exercice"), appraisal.ev_campagne_id.exercice or ""),
            (_("Grille appliquée"), appraisal.ev_grille_id.name or ""),
            (_("État de l'évaluation"), etats.get(appraisal.state,
                                                  appraisal.state or "")),
            (_("Date d'entretien"), self._date_locale(appraisal.date_close)),
        ]

    # ------------------------------------------------------------------
    # Récapitulatif d'une campagne
    # ------------------------------------------------------------------
    def recapitulatif_campagne(self, campagne):
        """Classeur d'une campagne : une ligne par agent, une colonne par
        critère. C'est la matière première des analyses RH."""
        self._check_xlsxwriter()
        campagne.ensure_one()
        flux = io.BytesIO()
        classeur = xlsxwriter.Workbook(flux, {"in_memory": True})
        f = _styles(classeur)

        evaluations = self.env["hr.appraisal"].search(
            [("ev_campagne_id", "=", campagne.id)],
            order="employee_id")
        criteres = campagne.grille_id.critere_ids

        feuille = classeur.add_worksheet(_("Récapitulatif"))
        feuille.set_landscape()
        feuille.set_paper(9)
        feuille.freeze_panes(5, 2)

        feuille.write(0, 0, campagne.name or "", f["titre"])
        feuille.write(1, 0, _(
            "Exercice %(ex)s — grille « %(grille)s » — %(nb)s évaluation(s)",
            ex=campagne.exercice or "-",
            grille=campagne.grille_id.name or "-",
            nb=len(evaluations)), f["soustitre"])

        entetes = [
            (_("Agent"), 30), (_("Département"), 26), (_("Poste"), 24),
            (_("Supérieur (N+1)"), 26), (_("État"), 14),
            (_("Phase en cours"), 22), (_("En attente de"), 24),
            (_("Critères notés"), 10), (_("Note globale"), 11),
        ]
        ligne = 4
        for colonne, (titre, largeur) in enumerate(entetes):
            feuille.set_column(colonne, colonne, largeur)
            feuille.write(ligne, colonne, titre, f["entete"])
        decalage = len(entetes)
        for index, critere in enumerate(criteres):
            colonne = decalage + index
            feuille.set_column(colonne, colonne, 16)
            feuille.write(ligne, colonne, "%s\n(%s)" % (
                critere.name or "", critere.theme_id.name or ""),
                f["entete"])
        feuille.set_row(ligne, 58)
        ligne += 1

        etats = dict(self.env["hr.appraisal"]._fields["state"].selection)
        for appraisal in evaluations:
            employee = appraisal.employee_id
            notes = {n.critere_id.id: n for n in appraisal.ev_note_ids}
            feuille.write(ligne, 0, employee.name or "", f["critere"])
            feuille.write(ligne, 1, employee.department_id.name or "",
                          f["critere"])
            feuille.write(ligne, 2,
                          employee.job_title or employee.job_id.name or "",
                          f["critere"])
            feuille.write(ligne, 3, employee.parent_id.name or "", f["critere"])
            feuille.write(ligne, 4, etats.get(appraisal.state,
                                              appraisal.state or ""),
                          f["critere"])
            feuille.write(ligne, 5,
                          appraisal.ev_phase_courante_id.name or "", f["critere"])
            feuille.write(ligne, 6,
                          appraisal.ev_acteur_courant_id.name or "", f["critere"])
            feuille.write(ligne, 7, "%s / %s" % (appraisal.ev_nb_notes,
                                                 appraisal.ev_nb_criteres),
                          f["vide"])
            if appraisal.ev_nb_notes:
                feuille.write_number(ligne, 8,
                                     round(appraisal.ev_note_globale, 2),
                                     f["total"])
            else:
                feuille.write(ligne, 8, "—", f["vide"])
            for index, critere in enumerate(criteres):
                note = notes.get(critere.id)
                if note and note.niveau_manager_id:
                    feuille.write_number(ligne, decalage + index,
                                         note.valeur_manager, f["nombre"])
                else:
                    feuille.write(ligne, decalage + index, "", f["vide"])
            ligne += 1

        if not evaluations:
            feuille.write(ligne, 0, _(
                "Cette campagne n'a encore généré aucune évaluation."),
                f["soustitre"])

        self._feuille_grille(classeur, f, campagne.grille_id)
        classeur.close()
        flux.seek(0)
        return (_("Recapitulatif - %s.xlsx",
                  self._nettoyer(campagne.name)), flux.read())

    def _feuille_grille(self, classeur, f, grille):
        """Second onglet : la grille appliquée, pour que le classeur se lise
        seul. Aucune pondération à afficher : à chaque niveau, tout compte
        également (moyennes simples)."""
        if not grille:
            return
        feuille = classeur.add_worksheet(_("Grille appliquée"))
        feuille.set_column(0, 0, 62)
        feuille.write(0, 0, grille.name or "", f["titre"])
        feuille.write(1, 0, _(
            "Note d'un thème = moyenne de ses critères ; note d'un bloc = "
            "moyenne de ses thèmes ; note globale = moyenne des blocs."),
            f["texte"])
        ligne = 3
        feuille.write(ligne, 0, _("Bloc / Thème / Critère"), f["entete"])
        ligne += 1
        for bloc in grille.bloc_ids:
            feuille.write(ligne, 0, bloc.name or "", f["rubrique"])
            ligne += 1
            for theme in bloc.theme_ids:
                feuille.write(ligne, 0, "    %s" % (theme.name or ""),
                              f["sous_rubrique"])
                ligne += 1
                for critere in theme.critere_ids:
                    feuille.write(ligne, 0, "        %s" % (critere.name or ""),
                                  f["critere"])
                    ligne += 1

    # ------------------------------------------------------------------
    # Utilitaires
    # ------------------------------------------------------------------
    def _date_locale(self, valeur):
        if not valeur:
            return ""
        return str(valeur)[:16]

    def _texte_depuis_html(self, valeur):
        """Le contenu d'un champ HTML, rendu lisible dans une cellule :
        les fins de paragraphe deviennent des sauts de ligne, les balises
        disparaissent, les entités sont rétablies."""
        if not valeur:
            return ""
        saut = chr(10)
        texte = re.sub(r"<\s*br\s*/?>", saut, valeur, flags=re.I)
        texte = re.sub(r"</\s*(p|div|li|h[1-6]|tr)\s*>", saut, texte,
                       flags=re.I)
        texte = re.sub(r"<[^>]+>", "", texte)
        texte = html.unescape(texte)
        lignes = [l.strip() for l in texte.splitlines()]
        return saut.join(l for l in lignes if l).strip()

    def _nettoyer(self, texte):
        """Un nom de fichier sans caractère interdit par Windows."""
        propre = "".join(
            c for c in (texte or "")
            if c.isalnum() or c in " -_àâäéèêëïîôöùûüçÀÂÄÉÈÊËÏÎÔÖÙÛÜÇ")
        return (propre.strip() or _("export"))[:60]
