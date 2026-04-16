# ACWORK

ACWORK est une stack d'orchestration moderne qui combine :

- `n8n` comme orchestrateur de workflows.
- `FastAPI` comme backend asynchrone.
- `PostgreSQL` pour la persistance.
- `Redis` pour Celery (broker + backend).
- `Celery` pour l'exécution de tâches en arrière-plan.
- `Nginx` pour le reverse proxy et le SSL.

Ce dépôt fournit un service API pour créer, suivre et traiter des tâches métiers, avec une intégration bidirectionnelle entre FastAPI et n8n.

## Documentation complète

La documentation complète et le rapport détaillé du projet sont disponibles dans :

- `docs/project-report.md`

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                      Internet                       │
└───────────────────┬─────────────────────────────────┘
                    │ 80/443
           ┌────────▼────────┐
           │     Nginx       │  reverse proxy + SSL
           └──┬──────────┬───┘
              │          │
     ┌────────▼──┐  ┌────▼──────┐
     │   n8n     │  │  FastAPI  │
     │ :5678     │  │  :8000    │
     └─────┬─────┘  └─────┬─────┘
           │              │
           └──────┬───────┘
                  │
         ┌────────▼────────┐
         │   PostgreSQL    │
         │  n8n_db appdb   │
         └─────────────────┘
```

## Quick start — local development

```bash
git clone <repo> && cd ACWORK
make local-setup
make migrate
```

Puis ouvrir :

- `http://localhost:5678` pour n8n
- `http://localhost:8000` pour l'API
- `http://localhost:8000/docs` pour la documentation OpenAPI

## Commandes clés

| Command | Description |
|---|---|
| `make local-setup` | Copier `.env.local` → `.env` et démarrer la stack locale |
| `make local-up` | Démarrer les services en mode développement |
| `make local-down` | Arrêter la stack |
| `make local-logs` | Afficher les logs des services |
| `make up` | Démarrer en mode production |
| `make down` | Arrêter en mode production |
| `make migrate` | Appliquer les migrations Alembic |
| `make migrate-create MSG='...'` | Générer une nouvelle migration |
| `make shell-api` | Ouvrir un shell dans le container API |
| `make shell-db` | Ouvrir `psql` dans la base `appdb` |
| `make test-local` | Exécuter les tests localement avec SQLite |
| `make lint-local` | Linter et formater le code localement |

## Démarrage production

1. Copier `.env.example` en `.env` et remplir les valeurs.
2. Placer les certificats SSL dans `nginx/ssl/`.
3. Ajuster les fichiers `nginx/conf.d/*.conf` avec le ou les domaines.
4. Lancer :

```bash
make up
make migrate
```

## Structure du projet

```
.
├── docker-compose.yml          # Production services
├── docker-compose.override.yml # Dev overrides
├── .env.example                # Modèle de configuration
├── .env.local                  # Configuration locale prête à l'emploi
├── Makefile                    # Raccourcis de commandes
├── nginx/                      # Reverse proxy et SSL
├── postgres/                   # Initialisation des bases de données
├── api/                        # Backend FastAPI + Celery + migrations
├── docs/                       # Documentation du projet
├── monitoring/                 # Prometheus / Grafana
├── n8n/                        # Workflows n8n
└── scripts/                    # Utilitaires d'administration
```

## API et intégration n8n

Le backend expose un ensemble de routes sous `/api/v1` :

- `GET /health` — état du service et dépendances
- `GET /ping` — probe simple de l'API
- `POST /tasks/` — créer une tâche et lancer son exécution
- `GET /tasks/` — lister les tâches
- `GET /tasks/{task_id}` — lire le statut d'une tâche
- `PATCH /tasks/{task_id}` — mettre à jour une tâche existante
- `DELETE /tasks/{task_id}` — supprimer une tâche
- `POST /tasks/{task_id}/trigger-n8n` — redéclencher un webhook n8n avec le payload enregistré

## Concept de tâches

Chaque tâche est sauvegardée en base de données dans le modèle `Task` et passe par un cycle de vie :

- `pending`
- `running`
- `success`
- `failed`
- `cancelled`

La logique métier est exécutée en arrière-plan par Celery, puis les résultats sont persistés.

## Monitoring

- Métriques Prometheus disponibles sur `/metrics`.
- Dashboards Grafana fournis dans `monitoring/grafana/`.
- Logs structurés via `structlog`.

## Ajouter un nouveau type de tâche

1. Ajouter un handler dans `api/app/workers/tasks.py`.
2. Ajouter le type dans le dictionnaire `handlers` de `_dispatch()`.
3. La nouvelle tâche sera traitée par l'architecture Celery existante.

## Documentation détaillée

Pour une description complète du projet, consulter :

- `docs/project-report.md`
| `TIMEZONE` | no | e.g. `Europe/Paris` |
