import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import AsyncAdaptedQueuePool
import logging
from ..config import settings

logger = logging.getLogger(__name__)

class DatabasePool:
    def __init__(self):
        self.engine = None
        self.session_factory = None
        
    async def initialize(self):
        """Initialize database connection pool"""
        # FIX (FINDINGS.md 1.2): make initialize() idempotent so the shared global
        # pool can be safely reused across requests (previously a new pool was built
        # per request and never disposed). Failed attempts stay retryable.
        if self.session_factory:
            return
        try:
            # FIX (FINDINGS.md 1.2): build the connection URL from settings.database_url
            # (docker-compose DATABASE_URL, e.g. postgresql://postgres:postgres@db:5432/propertyflow).
            # The old code read settings.supabase_db_user/password/host/port/name, which do
            # not exist in config.py - every initialize() raised AttributeError, left
            # session_factory as None, and the revenue service fell back to mock data.
            database_url = settings.database_url

            # Point SQLAlchemy at the asyncpg driver while keeping the configured URL intact.
            if database_url.startswith("postgresql+asyncpg://"):
                pass
            elif database_url.startswith("postgres://"):
                database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)
            elif database_url.startswith("postgresql://"):
                database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
            else:
                raise ValueError(
                    f"Unsupported DATABASE_URL scheme (expected postgresql://): {database_url.split('://')[0]}://"
                )

            self.engine = create_async_engine(
                database_url,
                # FIX (FINDINGS.md 1.2): QueuePool cannot be used with an asyncio engine -
                # SQLAlchemy rejected it ("Pool class QueuePool cannot be used with asyncio
                # engine"), which was a second reason pool initialization always failed.
                # AsyncAdaptedQueuePool is the async-safe equivalent and keeps the same
                # pool_size/max_overflow tuning.
                poolclass=AsyncAdaptedQueuePool,
                pool_size=20,  # Number of connections to maintain
                max_overflow=30,  # Additional connections when needed
                pool_pre_ping=True,  # Validate connections
                pool_recycle=3600,  # Recycle connections every hour
                echo=False  # Set to True for SQL debugging
            )
            
            self.session_factory = async_sessionmaker(
                bind=self.engine,
                class_=AsyncSession,
                expire_on_commit=False
            )
            
            logger.info("✅ Database connection pool initialized")
            
        except Exception as e:
            logger.error(f"❌ Database pool initialization failed: {e}")
            self.engine = None
            self.session_factory = None
    
    async def close(self):
        """Close database connections"""
        if self.engine:
            await self.engine.dispose()
    
    # FIX (FINDINGS.md 1.2): this was previously `async def`, so callers doing
    # `async with db_pool.get_session() as session:` received a coroutine instead of
    # a session ("'coroutine' object does not support the asynchronous context manager
    # protocol"). The bug was masked because session_factory was always None (see URL
    # bug above). AsyncSession is itself the async context manager, so return it directly.
    def get_session(self) -> AsyncSession:
        """Get a database session from the pool"""
        if not self.session_factory:
            raise RuntimeError("Database pool not initialized")
        return self.session_factory()

# Global database pool instance
db_pool = DatabasePool()

async def get_db_session() -> AsyncSession:
    """Dependency to get database session"""
    async with db_pool.get_session() as session:
        yield session
