
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.bash import BashOperator

# ─── Paramètres par défaut du DAG ────────────────────────────────────────────
# Ces paramètres s'appliquent à toutes les tâches sauf indication contraire
parametres_defaut = {
    "owner": "data_team",
    "depends_on_past": False,       # chaque exécution est indépendante
    "email_on_failure": True,       # alerte email si une tâche plante
    "email": ["data@pricetracker.fr"],
    "retries": 2,                   # on réessaie 2 fois en cas d'échec
    "retry_delay": timedelta(minutes=5),  # 5 minutes entre les tentatives
}

# ─── Définition du DAG ───────────────────────────────────────────────────────
with DAG(
    dag_id="pipeline_pricetracker_quotidien",
    description="Pipeline complet : ingestion → transformation → tests",
    default_args=parametres_defaut,
    schedule="0 6 * * *",          # tous les jours à 6h00 (format cron)
    start_date=datetime(2025, 1, 1),
    catchup=False,                  # ne pas rejouer les exécutions passées
    tags=["pricetracker", "quotidien"],
) as dag:

    # ─── TÂCHE 1 : Télécharger Open Prices ───────────────────────────────────
    # PythonOperator exécute une fonction Python directement
    tache_open_prices = PythonOperator(
        task_id="telecharger_open_prices",
        python_callable=telecharger_open_prices,  # fonction dans load_open_prices.py
        doc_md="""
        Télécharge le dataset Open Prices depuis HuggingFace.
        Durée estimée : 2-5 minutes selon la connexion.
        """,
    )

    # ─── TÂCHE 2 : Télécharger INSEE ─────────────────────────────────────────
    tache_insee = PythonOperator(
        task_id="telecharger_insee",
        python_callable=fetch_ipc_insee,
        doc_md="Récupère les indices IPC depuis l'API INSEE.",
    )

    # ─── TÂCHE 3 : Transformer avec dbt ──────────────────────────────────────
    # BashOperator exécute une commande shell
    # dbt run exécute tous les modèles SQL dans l'ordre des dépendances
    tache_dbt_run = BashOperator(
        task_id="dbt_transformation",
        bash_command="cd /opt/airflow/transform && dbt run --profiles-dir .",
        doc_md="""
        Lance dbt pour transformer les données brutes en modèle en étoile.
        Crée/met à jour toutes les tables dim_* et fact_price.
        """,
    )

    # ─── TÂCHE 4 : Tests de qualité ──────────────────────────────────────────
    # dbt test vérifie toutes les règles définies dans schema.yml
    tache_dbt_test = BashOperator(
        task_id="tests_qualite",
        bash_command="cd /opt/airflow/transform && dbt test --profiles-dir .",
        doc_md="""
        Vérifie la qualité des données :
        - Pas de valeurs nulles dans les colonnes obligatoires
        - Prix entre 0 et 10 000 €
        - Intégrité des clés étrangères
        """,
    )

    # ─── ORDRE D'EXÉCUTION ────────────────────────────────────────────────────
    # >> signifie "s'exécute avant"
    # Les tâches 1 et 2 s'exécutent en PARALLÈLE (gain de temps)
    # La tâche 3 attend que 1 ET 2 soient terminées
    # La tâche 4 attend que 3 soit terminée
    [tache_open_prices, tache_insee] >> tache_dbt_run >> tache_dbt_test