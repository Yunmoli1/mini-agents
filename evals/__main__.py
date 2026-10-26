import asyncio
import sys

from .runner import amain

if __name__ == "__main__":
    asyncio.run(amain(sys.argv[1:]))
