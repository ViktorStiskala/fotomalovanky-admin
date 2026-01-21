"""Dramatiq background tasks package."""

# Import broker to configure it
import app.tasks.broker  # noqa: F401

# Import all tasks to register them with Dramatiq
import app.tasks.coloring.generate_coloring  # noqa: F401
import app.tasks.coloring.vectorize_image  # noqa: F401
import app.tasks.orders.fetch_shopify_order  # noqa: F401
import app.tasks.orders.image_download  # noqa: F401
import app.tasks.utils.recovery  # noqa: F401  # run_recovery task
