"""Import all model modules so SQLAlchemy's metadata is fully populated.

Alembic autogenerate and ``Base.metadata.create_all`` rely on every model
class being imported/registered, which importing the submodules guarantees.
"""

from app.models import (  # noqa: F401
    auth,
    finance,
    inventory,
    purchase,
    sales,
    tenant,
)
