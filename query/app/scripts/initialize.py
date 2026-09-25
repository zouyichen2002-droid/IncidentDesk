"""Initialize an empty index exactly once; never reset warehouse business data."""
import asyncio
from pathlib import Path
from sqlalchemy import text
from app.clients.mysql_client_manager import meta_mysql_client_manager as manager
from app.scripts.build_meta_knowledge import build

async def main():
    manager.init()
    async with manager.session_factory() as session:
        await session.execute(text('CREATE TABLE IF NOT EXISTS knowledge_build (id INT PRIMARY KEY, version VARCHAR(100) NOT NULL)'))
        await session.commit()
        version = (await session.execute(text('SELECT version FROM knowledge_build WHERE id=1'))).scalar()
        if version == 'merged-v1':
            print('Knowledge already initialized: merged-v1')
            await manager.close()
            return
        count = (await session.execute(text('SELECT COUNT(*) FROM table_info'))).scalar()
        if count:
            raise RuntimeError('Metadata is partially initialized. Preserve data and repair the index before retrying.')
    await manager.close()
    await build(Path('conf/meta_config.yaml'))
    manager.init()
    async with manager.session_factory() as session:
        await session.execute(text("INSERT INTO knowledge_build VALUES(1,'merged-v1')"))
        await session.commit()
    await manager.close()
    print('Knowledge initialized: merged-v1')

if __name__ == '__main__':
    asyncio.run(main())
