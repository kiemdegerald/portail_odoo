# -*- coding: utf-8 -*-
"""Fiche d'imputation comptable d'une mission (format Excel).

Reproduit la fiche utilisée par la banque (cf. « FICHE D'IMPUTATION
COMPTABLE » réelle de l'ordre de mission N°029/2026/BADF) :

    DÉBIT   compte de charge          <- part « perdiems »
    DÉBIT   compte à justifier        <- part « autres frais »
    CRÉDIT  compte de chaque missionnaire (son montant)

Les comptes, intitulés, service émetteur et libellé de visa sont
PARAMÉTRABLES par société (Paramètres > Missions), car ils varient selon
le service émetteur (SCH / DCH) et l'organisation.
"""
import io
from datetime import datetime, time

from odoo import fields, models, _
from odoo.exceptions import UserError

try:
    import xlsxwriter
except ImportError:  # pragma: no cover - dépendance standard d'Odoo
    xlsxwriter = None


class GmMission(models.Model):
    _inherit = "gm.mission"

    # ------------------------------------------------------------------
    # Données de la fiche
    # ------------------------------------------------------------------
    def _imputation_stage(self):
        """Ce que la fiche met en paiement : l'AVANCE avant le départ, le
        SOLDE une fois le retour déclaré."""
        self.ensure_one()
        return "solde" if self.state in ("returned", "closed") else "avance"

    @staticmethod
    def _split_compte(acc_number):
        """« 01001-00200315850-50 » -> ('01001', '00200315850-50»).
        Le format bancaire de la BADF préfixe le numéro par le code
        agence ; sans préfixe, le code agence est laissé vide."""
        acc = (acc_number or "").strip()
        if "-" in acc:
            tete, reste = acc.split("-", 1)
            if tete.isdigit() and len(tete) <= 5:
                return tete, reste
        return "", acc

    def _imputation_lignes(self):
        """Lignes de la fiche : (code agence, compte, intitulé, débit,
        crédit).

        Deux sens possibles :
        * DÉCAISSEMENT (avance, ou solde positif au retour) — les comptes
          de charge sont débités, les missionnaires crédités ;
        * RÉCUPÉRATION (solde négatif : trop-perçu après un retour
          anticipé) — l'écriture s'inverse, les missionnaires sont
          débités et la charge créditée d'autant.
        Les montants de charge sont ventilés dans la même proportion que
        ce qui est réellement mouvementé pour chaque missionnaire : la
        fiche est donc toujours équilibrée.
        """
        self.ensure_one()
        stage = self._imputation_stage()
        devise = self.currency_id
        charge_net = justifier_net = 0.0
        lignes_membres = []

        for membre in self.membre_ids:
            montant = (membre.avance_montant if stage == "avance"
                       else membre.solde)
            if devise.is_zero(montant):
                continue
            base = membre.total_du or 0.0
            ratio = (abs(montant) / base) if base else 0.0
            sens = 1.0 if montant > 0 else -1.0
            charge_net += membre.indemnite_total * ratio * sens
            justifier_net += membre.autres_frais * ratio * sens
            code_agence, compte = self._split_compte(membre.compte_bancaire)
            if not compte:
                raise UserError(_(
                    "Aucun compte bancaire n'est connu pour %s : impossible "
                    "de l'imputer. Complétez sa fiche employé, ou sa fiche "
                    "dans le répertoire des chauffeurs.",
                    membre.nom_affiche or ""))
            valeur = devise.round(abs(montant))
            lignes_membres.append((
                code_agence, compte, (membre.nom_affiche or "").upper(),
                valeur if montant < 0 else 0.0,      # trop-perçu : débit
                valeur if montant > 0 else 0.0))     # décaissement : crédit

        if not lignes_membres:
            raise UserError(_(
                "Rien à imputer pour cette mission : le solde est nul, "
                "l'opération a déjà été soldée par la fiche d'avance."))

        company = self.company_id
        lignes = []

        def _ligne_compte(agence, compte, libelle, net):
            """Place un montant net dans la bonne colonne : positif au
            débit (charge constatée), négatif au crédit (charge
            annulée)."""
            if devise.is_zero(net):
                return
            lignes.append((agence, compte or "", libelle or "",
                           net if net > 0 else 0.0,
                           -net if net < 0 else 0.0))

        # La ventilation par nature est une répartition : on arrondit la
        # part « à justifier » puis on déduit la charge du TOTAL réellement
        # mouvementé. La fiche tombe ainsi juste au centime près, sans
        # écart d'arrondi à absorber.
        total_net = sum(
            (credit - debit) for _a, _c, _l, debit, credit in lignes_membres)
        justifier_net = devise.round(justifier_net)
        charge_net = devise.round(total_net - justifier_net)

        _ligne_compte(company.gm_imput_agence_siege or "",
                      company.gm_imput_compte_charge,
                      company.gm_imput_libelle_charge, charge_net)
        _ligne_compte(lignes_membres[0][0],
                      company.gm_imput_compte_justifier,
                      company.gm_imput_libelle_justifier, justifier_net)
        return lignes + lignes_membres, stage

    # ------------------------------------------------------------------
    # Génération du classeur
    # ------------------------------------------------------------------
    def _build_imputation_xlsx(self):
        self.ensure_one()
        if xlsxwriter is None:
            raise UserError(_(
                "La génération Excel est indisponible sur ce serveur "
                "(bibliothèque xlsxwriter absente)."))
        lignes, stage = self._imputation_lignes()
        company = self.company_id

        flux = io.BytesIO()
        classeur = xlsxwriter.Workbook(flux, {"in_memory": True})
        feuille = classeur.add_worksheet("Imputation")

        titre = classeur.add_format({"bold": True, "font_size": 12})
        gras = classeur.add_format({"bold": True})
        entete = classeur.add_format({
            "bold": True, "border": 1, "align": "center", "valign": "vcenter",
            "text_wrap": True, "bg_color": "#D9D9D9"})
        cellule = classeur.add_format({"border": 1})
        montant = classeur.add_format({"border": 1, "num_format": "#,##0"})
        total = classeur.add_format({
            "border": 1, "bold": True, "num_format": "#,##0"})
        date_fmt = classeur.add_format({"num_format": "dd/mm/yyyy",
                                        "align": "right"})

        feuille.set_column("A:A", 12)
        feuille.set_column("B:B", 20)
        feuille.set_column("C:C", 38)
        feuille.set_column("D:E", 14)

        feuille.write("A1", company.name or "", titre)
        feuille.write("A2", company.gm_imput_service or "", gras)
        feuille.write("A3", "FICHE D'IMPUTATION COMPTABLE", titre)
        feuille.write_datetime(
            "D4",
            datetime.combine(fields.Date.context_today(self), time()),
            date_fmt)

        ligne = 4
        for col, libelle in enumerate(
                ["Codes Agence", "N° Comptes", "Intitulés de Comptes",
                 "Mt débit", "Mt crédit"]):
            feuille.write(ligne, col, libelle, entete)

        total_debit = total_credit = 0.0
        for agence, compte, libelle, debit, credit in lignes:
            ligne += 1
            feuille.write(ligne, 0, agence, cellule)
            feuille.write(ligne, 1, compte, cellule)
            feuille.write(ligne, 2, libelle, cellule)
            feuille.write_number(ligne, 3, debit or 0, montant)
            feuille.write_number(ligne, 4, credit or 0, montant)
            total_debit += debit or 0
            total_credit += credit or 0

        ligne += 1
        feuille.write(ligne, 2, "TOTAUX", total)
        feuille.write_number(ligne, 3, total_debit, total)
        feuille.write_number(ligne, 4, total_credit, total)

        ligne += 2
        suffixe = ""
        if stage == "solde":
            suffixe = (_(" - TROP-PERÇU A RECUPERER") if self.solde < 0
                       else _(" - SOLDE"))
        feuille.write(ligne, 0, "Libellé :", gras)
        feuille.write(ligne, 1, "FRAIS DE MISSION N°%s%s" % (
            self.name or "", suffixe))
        ligne += 2
        feuille.write(ligne, 0, company.gm_imput_visa or "", gras)
        ligne += 2
        feuille.write(ligne, 0, "Demandé par :", gras)
        feuille.write(ligne, 3, "Approuvé par :", gras)
        ligne += 2
        feuille.write(ligne, 0, "Vérifié par :", gras)

        classeur.close()
        return flux.getvalue()

    def action_imputation_xlsx(self):
        """Bouton du formulaire : télécharge la fiche d'imputation."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": "/gm/mission/%s/imputation.xlsx" % self.id,
            "target": "self",
        }
