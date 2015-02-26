SET statement_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET client_min_messages = warning;

CREATE USER dhcp WITH PASSWORD 'dhcp';

CREATE DATABASE dhcp WITH TEMPLATE = template0 ENCODING = 'UTF8' LC_COLLATE = 'en_GB.UTF-8' LC_CTYPE = 'en_GB.UTF-8';


ALTER DATABASE dhcp OWNER TO dhcp;

\connect dhcp

SET statement_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET client_min_messages = warning;
CREATE EXTENSION IF NOT EXISTS plpgsql WITH SCHEMA pg_catalog;
SET search_path = public, pg_catalog;

SET default_tablespace = '';

SET default_with_oids = false;
CREATE TABLE leases (
    addr inet NOT NULL,
    mac character varying(20),
    expiry integer,
    interface character varying(20)
);

CREATE TABLE blocks (
    mac character varying(20),
    blockuser character varying(20)
);


ALTER TABLE public.leases OWNER TO dhcp;
ALTER TABLE public.blocks OWNER TO dhcp;
ALTER TABLE ONLY blocks ADD CONSTRAINT pkeymac PRIMARY KEY (mac);
ALTER TABLE ONLY leases ADD CONSTRAINT pkey PRIMARY KEY (addr);
CREATE INDEX idx_expiry ON leases USING btree (expiry);
CREATE INDEX idx_mac ON leases USING btree (mac);
ALTER TABLE leases ADD COLUMN reserved character varying(20);
ALTER TABLE leases ADD COLUMN reservedtime integer;
ALTER TABLE leases ADD COLUMN reservedname character varying(50);
ALTER TABLE leases ADD COLUMN leasestart integer;
CREATE INDEX idx_leasestart ON leases USING btree(leasestart);
