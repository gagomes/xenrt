import waitress
import server
waitress.serve(server.ServerInstance().getApp(), host='0.0.0.0', port=8080, threads=64)
