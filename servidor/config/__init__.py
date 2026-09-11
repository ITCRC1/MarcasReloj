"""Driver de MySQL.

En Windows se usa `mysqlclient`, que trae rueda precompilada. En Linux, y por lo
tanto en Railway, `mysqlclient` hay que compilarlo y eso suele fallar en el
constructor. PyMySQL es Python puro, instala en cualquier lado y se hace pasar por
MySQLdb, asi que Django no nota la diferencia.

Se prefiere mysqlclient si esta; PyMySQL entra solo cuando no.
"""

try:
    import MySQLdb  # noqa: F401
except ImportError:  # pragma: no cover - depende del sistema, no de la logica
    try:
        import pymysql

        pymysql.install_as_MySQLdb()
    except ImportError:
        # Sin ningun driver de MySQL. No importa si la base es SQLite o Postgres.
        pass
