# -*- coding: utf-8 -*-
from . import models
from . import controllers

# Types cochés « Proposé sur le portail » par défaut à l'installation, s'ils
# existent sur la base (nom -> réglages complémentaires). Ne s'applique que
# si AUCUN type n'est encore publié : ensuite, la main est aux RH.
# « Congé maladie » autorise les dates passées (arrêt régularisé au retour).
DEFAULT_PORTAL_LEAVE_TYPES = {
    "Congés payés": {},
    "Congé maladie": {"portail_allow_past_dates": True},
    "Congés de maternité": {"portail_label": "Congé de maternité"},
    "Absence déductible": {"portail_label": "Congé absence"},
}


def _enable_default_portal_leave_types(env):
    LeaveType = env["hr.leave.type"]
    if LeaveType.search_count([("portail_published", "=", True)]):
        return
    # Le nom des types est traduit (jsonb) : on cherche dans TOUTES les
    # langues installées (ex. type renommé « Congés payés » en français
    # seulement — introuvable dans la langue par défaut de l'environnement).
    langs = [code for code, _name in env["res.lang"].get_installed()]
    for name, extra_vals in DEFAULT_PORTAL_LEAVE_TYPES.items():
        for lang in langs:
            leave_type = LeaveType.with_context(lang=lang).search(
                [("name", "=ilike", name)], limit=1)
            if leave_type:
                leave_type.write(dict(portail_published=True, **extra_vals))
                break


def post_init_hook(env):
    """Ajoute le menu « Demande de congés » au(x) site(s) web existant(s).

    La page elle-même est créée par data/website_page.xml ; le menu, lui,
    doit exister pour CHAQUE site web (les menus sont par site), ce qu'un
    enregistrement XML statique ne sait pas faire. Idempotent : ne crée
    rien si un menu pointe déjà vers la page. Le menu se masque
    automatiquement pour les visiteurs non connectés (la page est en
    visibilité « connectés »).
    """
    _enable_default_portal_leave_types(env)
    # Recopie le paramètre email RH dans le formulaire de la page (au cas où
    # il aurait été défini avant/pendant l'installation).
    env["ir.config_parameter"]._portail_sync_leave_form_email()
    page = env.ref("portail.page_demande_de_conges", raise_if_not_found=False)
    if not page:
        return
    Menu = env["website.menu"]
    for website in env["website"].search([]):
        already = Menu.search([
            ("website_id", "=", website.id),
            ("url", "=", page.url),
        ], limit=1)
        if already:
            continue
        top_menu = Menu.search([
            ("website_id", "=", website.id),
            ("parent_id", "=", False),
        ], limit=1)
        if not top_menu:
            continue
        Menu.create({
            "name": "Demande de congés",
            "url": page.url,
            "page_id": page.id,
            "parent_id": top_menu.id,
            "website_id": website.id,
            "sequence": 50,
        })
