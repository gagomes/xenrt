import waitress
import server
waitress.serve(server.ServerInstance().getApp(), host='0.0.0.0', port=1025, threads=64)
