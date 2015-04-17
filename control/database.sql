--
-- PostgreSQL database dump
--

SET statement_timeout = 0;
SET lock_timeout = 0;
SET client_encoding = 'LATIN1';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET client_min_messages = warning;

--
-- Name: plpgsql; Type: EXTENSION; Schema: -; Owner: 
--

CREATE EXTENSION IF NOT EXISTS plpgsql WITH SCHEMA pg_catalog;


--
-- Name: EXTENSION plpgsql; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION plpgsql IS 'PL/pgSQL procedural language';


SET search_path = public, pg_catalog;

--
-- Name: atof(character varying); Type: FUNCTION; Schema: public; Owner: xenrtd
--

CREATE FUNCTION atof(character varying) RETURNS double precision
    LANGUAGE sql STRICT
    AS $_$select
$1::text::float$_$;


ALTER FUNCTION public.atof(character varying) OWNER TO xenrtd;

--
-- Name: to_array(anyelement); Type: AGGREGATE; Schema: public; Owner: xenrtd
--

CREATE AGGREGATE to_array(anyelement) (
    SFUNC = array_append,
    STYPE = anyarray,
    INITCOND = '{}'
);


ALTER AGGREGATE public.to_array(anyelement) OWNER TO xenrtd;

--
-- Name: jobid_seq; Type: SEQUENCE; Schema: public; Owner: xenrtd
--

CREATE SEQUENCE jobid_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.jobid_seq OWNER TO xenrtd;

--
-- Name: perf_perfid_seq; Type: SEQUENCE; Schema: public; Owner: xenrtd
--

CREATE SEQUENCE perf_perfid_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.perf_perfid_seq OWNER TO xenrtd;

SET default_tablespace = '';

SET default_with_oids = false;

--
-- Name: resourcelock; Type: TABLE; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE TABLE resourcelock (
);


ALTER TABLE public.resourcelock OWNER TO xenrtd;

--
-- Name: schedulelock; Type: TABLE; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE TABLE schedulelock (
);


ALTER TABLE public.schedulelock OWNER TO xenrtd;

--
-- Name: serial; Type: SEQUENCE; Schema: public; Owner: xenrtd
--

CREATE SEQUENCE serial
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.serial OWNER TO xenrtd;

--
-- Name: tblallowedfailures; Type: TABLE; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE TABLE tblallowedfailures (
    sequence character(24) NOT NULL,
    caseset character(24) NOT NULL
);


ALTER TABLE public.tblallowedfailures OWNER TO xenrtd;

--
-- Name: tblcasesets; Type: TABLE; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE TABLE tblcasesets (
    caseset character(24) NOT NULL,
    tgroup character(24) NOT NULL,
    tcase character(48) NOT NULL,
    tcgroup character(48) DEFAULT 'ALL'::bpchar NOT NULL,
    subtcase character(48) DEFAULT 'ALL'::bpchar NOT NULL
);


ALTER TABLE public.tblcasesets OWNER TO xenrtd;

--
-- Name: tblconfig; Type: TABLE; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE TABLE tblconfig (
    param character varying(64) NOT NULL,
    value character varying(64)
);


ALTER TABLE public.tblconfig OWNER TO xenrtd;

--
-- Name: tbldetails; Type: TABLE; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE TABLE tbldetails (
    detailid integer,
    ts timestamp without time zone,
    key character(24),
    value character(256)
);


ALTER TABLE public.tbldetails OWNER TO xenrtd;

--
-- Name: tblevents; Type: TABLE; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE TABLE tblevents (
    ts timestamp without time zone NOT NULL,
    etype character(24) NOT NULL,
    subject character(24) NOT NULL,
    edata character(32)
);


ALTER TABLE public.tblevents OWNER TO xenrtd;

--
-- Name: tbljobdetails; Type: TABLE; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE TABLE tbljobdetails (
    jobid integer NOT NULL,
    param character(24) NOT NULL,
    value character(256)
);


ALTER TABLE public.tbljobdetails OWNER TO xenrtd;

--
-- Name: tbljobgroups; Type: TABLE; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE TABLE tbljobgroups (
    gid character(24) NOT NULL,
    jobid integer NOT NULL,
    description character(24)
);


ALTER TABLE public.tbljobgroups OWNER TO xenrtd;

--
-- Name: tbljobs; Type: TABLE; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE TABLE tbljobs (
    jobid integer DEFAULT nextval(('jobid_seq'::text)::regclass) NOT NULL,
    version character(24),
    revision character(24),
    options character(12),
    jobstatus character(12),
    userid character(12),
    machine character(24),
    uploaded character(8),
    removed character(8)
);


ALTER TABLE public.tbljobs OWNER TO xenrtd;

--
-- Name: tblmachinedata; Type: TABLE; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE TABLE tblmachinedata (
    machine character(24) NOT NULL,
    key character(24) NOT NULL,
    value character(256)
);


ALTER TABLE public.tblmachinedata OWNER TO xenrtd;

--
-- Name: tblmachines; Type: TABLE; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE TABLE tblmachines (
    machine character(24) NOT NULL,
    site character(24),
    cluster character(24),
    pool character(24) DEFAULT 'DEFAULT'::bpchar,
    status character(16) DEFAULT 'idle'::bpchar,
    resources character(128),
    flags character(256),
    descr character(128),
    comment character(128),
    leaseto timestamp without time zone,
    jobid integer,
    leasereason character(128),
    leasefrom timestamp without time zone,
    leasepolicy integer
);


ALTER TABLE public.tblmachines OWNER TO xenrtd;

--
-- Name: tblpatchman; Type: TABLE; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE TABLE tblpatchman (
    gid integer DEFAULT nextval(('serial'::text)::regclass) NOT NULL,
    version character(24),
    revision character(24),
    level character(12),
    result character(12)
);


ALTER TABLE public.tblpatchman OWNER TO xenrtd;

--
-- Name: tblperf; Type: TABLE; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE TABLE tblperf (
    jobid integer,
    jobtype character(16),
    perfrun boolean,
    machine character(24),
    productname character(24),
    productspecial character(24),
    hvarch character(12),
    dom0arch character(12),
    hostdebug boolean,
    hostspecial character(32),
    guestname character(24),
    guesttype character(12),
    domaintype character(12),
    domainflags character(24),
    guestversion character(16),
    kernelversion character(64),
    kernelproductname character(24),
    kernelproductspecial character(24),
    guestarch character(12),
    guestdebug boolean,
    pvdrivers boolean,
    vcpus integer,
    memory integer,
    storagetype character(16),
    guestspecial character(32),
    alone boolean,
    benchmark character(24),
    bmversion character(24),
    bmspecial character(32),
    metric character(32),
    value double precision,
    units character(12),
    productversion character(32),
    kernelproductversion character(32),
    ts timestamp without time zone,
    guestnumber integer,
    extradisks integer,
    perfid integer DEFAULT nextval('perf_perfid_seq'::regclass) NOT NULL
);


ALTER TABLE public.tblperf OWNER TO xenrtd;

--
-- Name: tblresources; Type: TABLE; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE TABLE tblresources (
    name character(24) NOT NULL,
    site character(24),
    status character(16),
    jobid integer,
    data text,
    type character(24)
);


ALTER TABLE public.tblresources OWNER TO xenrtd;

--
-- Name: tblresults; Type: TABLE; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE TABLE tblresults (
    jobid integer NOT NULL,
    phase3 character(16),
    test3 character(24),
    result character(12),
    detailid integer NOT NULL,
    uploaded character(8),
    test character(32) NOT NULL,
    comment character(32),
    phase character(32) NOT NULL,
    phaseextn character varying(64),
    testextn character varying(64)
);


ALTER TABLE public.tblresults OWNER TO xenrtd;

--
-- Name: tblresults_detailid_seq; Type: SEQUENCE; Schema: public; Owner: xenrtd
--

CREATE SEQUENCE tblresults_detailid_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.tblresults_detailid_seq OWNER TO xenrtd;

--
-- Name: tblresults_detailid_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xenrtd
--

ALTER SEQUENCE tblresults_detailid_seq OWNED BY tblresults.detailid;


--
-- Name: tblrevisions; Type: TABLE; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE TABLE tblrevisions (
    version character(24) NOT NULL,
    revision character(24) NOT NULL,
    ts timestamp without time zone,
    hguser character(48),
    summary character(128)
);


ALTER TABLE public.tblrevisions OWNER TO xenrtd;

--
-- Name: tblsites; Type: TABLE; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE TABLE tblsites (
    site character(24) NOT NULL,
    status character(16) DEFAULT 'active'::bpchar,
    flags character(256),
    descr character(128),
    comment character(128),
    ctrladdr character(64),
    adminid character(16),
    maxjobs integer DEFAULT 20,
    sharedresources character(128)
);


ALTER TABLE public.tblsites OWNER TO xenrtd;

--
-- Name: tblsubresults; Type: TABLE; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE TABLE tblsubresults (
    detailid integer NOT NULL,
    subgroup character(48) NOT NULL,
    subtest character(48) NOT NULL,
    result character(12),
    subid integer NOT NULL,
    reason character(48),
    comment character(32)
);


ALTER TABLE public.tblsubresults OWNER TO xenrtd;

--
-- Name: tblsubresults_subid_seq; Type: SEQUENCE; Schema: public; Owner: xenrtd
--

CREATE SEQUENCE tblsubresults_subid_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.tblsubresults_subid_seq OWNER TO xenrtd;

--
-- Name: tblsubresults_subid_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xenrtd
--

ALTER SEQUENCE tblsubresults_subid_seq OWNED BY tblsubresults.subid;


--
-- Name: detailid; Type: DEFAULT; Schema: public; Owner: xenrtd
--

ALTER TABLE ONLY tblresults ALTER COLUMN detailid SET DEFAULT nextval('tblresults_detailid_seq'::regclass);


--
-- Name: subid; Type: DEFAULT; Schema: public; Owner: xenrtd
--

ALTER TABLE ONLY tblsubresults ALTER COLUMN subid SET DEFAULT nextval('tblsubresults_subid_seq'::regclass);


--
-- Name: config_pkey; Type: CONSTRAINT; Schema: public; Owner: xenrtd; Tablespace: 
--

ALTER TABLE ONLY tblconfig
    ADD CONSTRAINT config_pkey PRIMARY KEY (param);


--
-- Name: tblallowedfailures_pkey; Type: CONSTRAINT; Schema: public; Owner: xenrtd; Tablespace: 
--

ALTER TABLE ONLY tblallowedfailures
    ADD CONSTRAINT tblallowedfailures_pkey PRIMARY KEY (sequence, caseset);


--
-- Name: tblcasesets_pkey; Type: CONSTRAINT; Schema: public; Owner: xenrtd; Tablespace: 
--

ALTER TABLE ONLY tblcasesets
    ADD CONSTRAINT tblcasesets_pkey PRIMARY KEY (caseset, tgroup, tcase, tcgroup, subtcase);


--
-- Name: tblevents_pkey; Type: CONSTRAINT; Schema: public; Owner: xenrtd; Tablespace: 
--

ALTER TABLE ONLY tblevents
    ADD CONSTRAINT tblevents_pkey PRIMARY KEY (ts, etype, subject);


--
-- Name: tbljobdetails_pkey; Type: CONSTRAINT; Schema: public; Owner: xenrtd; Tablespace: 
--

ALTER TABLE ONLY tbljobdetails
    ADD CONSTRAINT tbljobdetails_pkey PRIMARY KEY (jobid, param);


--
-- Name: tbljobgroups_pkey; Type: CONSTRAINT; Schema: public; Owner: xenrtd; Tablespace: 
--

ALTER TABLE ONLY tbljobgroups
    ADD CONSTRAINT tbljobgroups_pkey PRIMARY KEY (gid, jobid);


--
-- Name: tbljobs_pkey; Type: CONSTRAINT; Schema: public; Owner: xenrtd; Tablespace: 
--

ALTER TABLE ONLY tbljobs
    ADD CONSTRAINT tbljobs_pkey PRIMARY KEY (jobid);


--
-- Name: tblmachinedata_pkey; Type: CONSTRAINT; Schema: public; Owner: xenrtd; Tablespace: 
--

ALTER TABLE ONLY tblmachinedata
    ADD CONSTRAINT tblmachinedata_pkey PRIMARY KEY (machine, key);


--
-- Name: tblmachines_pkey; Type: CONSTRAINT; Schema: public; Owner: xenrtd; Tablespace: 
--

ALTER TABLE ONLY tblmachines
    ADD CONSTRAINT tblmachines_pkey PRIMARY KEY (machine);


--
-- Name: tblpatchman_pkey; Type: CONSTRAINT; Schema: public; Owner: xenrtd; Tablespace: 
--

ALTER TABLE ONLY tblpatchman
    ADD CONSTRAINT tblpatchman_pkey PRIMARY KEY (gid);


--
-- Name: tblperf_pkey; Type: CONSTRAINT; Schema: public; Owner: xenrtd; Tablespace: 
--

ALTER TABLE ONLY tblperf
    ADD CONSTRAINT tblperf_pkey PRIMARY KEY (perfid);


--
-- Name: tblresources_pkey; Type: CONSTRAINT; Schema: public; Owner: xenrtd; Tablespace: 
--

ALTER TABLE ONLY tblresources
    ADD CONSTRAINT tblresources_pkey PRIMARY KEY (name);


--
-- Name: tblresults_pkey; Type: CONSTRAINT; Schema: public; Owner: xenrtd; Tablespace: 
--

ALTER TABLE ONLY tblresults
    ADD CONSTRAINT tblresults_pkey PRIMARY KEY (jobid, phase, test);


--
-- Name: tblrevisions_pkey; Type: CONSTRAINT; Schema: public; Owner: xenrtd; Tablespace: 
--

ALTER TABLE ONLY tblrevisions
    ADD CONSTRAINT tblrevisions_pkey PRIMARY KEY (version, revision);


--
-- Name: tblsites_pkey; Type: CONSTRAINT; Schema: public; Owner: xenrtd; Tablespace: 
--

ALTER TABLE ONLY tblsites
    ADD CONSTRAINT tblsites_pkey PRIMARY KEY (site);


--
-- Name: tblsubresults_pkey; Type: CONSTRAINT; Schema: public; Owner: xenrtd; Tablespace: 
--

ALTER TABLE ONLY tblsubresults
    ADD CONSTRAINT tblsubresults_pkey PRIMARY KEY (detailid, subgroup, subtest);


--
-- Name: idx_tbldetails_detailid; Type: INDEX; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE INDEX idx_tbldetails_detailid ON tbldetails USING btree (detailid);


--
-- Name: idx_tbldetails_detailid_key; Type: INDEX; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE INDEX idx_tbldetails_detailid_key ON tbldetails USING btree (detailid, key);


--
-- Name: idx_tbldetails_key; Type: INDEX; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE INDEX idx_tbldetails_key ON tbldetails USING btree (key);


--
-- Name: idx_tblpatchman_version_revision; Type: INDEX; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE INDEX idx_tblpatchman_version_revision ON tblpatchman USING btree (version, revision);


--
-- Name: idx_tblpatchman_version_revision_level_result; Type: INDEX; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE INDEX idx_tblpatchman_version_revision_level_result ON tblpatchman USING btree (version, revision, level, result);


--
-- Name: idx_tblsubresults_subid; Type: INDEX; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE INDEX idx_tblsubresults_subid ON tblsubresults USING btree (subid);


--
-- Name: tblcasesets_caseset; Type: INDEX; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE INDEX tblcasesets_caseset ON tblcasesets USING btree (caseset);


--
-- Name: tbldetails_index_detailid; Type: INDEX; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE INDEX tbldetails_index_detailid ON tbldetails USING btree (detailid);


--
-- Name: tbljobdetails_index_jobid; Type: INDEX; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE INDEX tbljobdetails_index_jobid ON tbljobdetails USING btree (jobid);


--
-- Name: tbljobdetails_index_param; Type: INDEX; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE INDEX tbljobdetails_index_param ON tbljobdetails USING btree (param);


--
-- Name: tbljobs_idx_jobstatus; Type: INDEX; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE INDEX tbljobs_idx_jobstatus ON tbljobs USING btree (jobstatus);


--
-- Name: tbljobs_idx_removed; Type: INDEX; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE INDEX tbljobs_idx_removed ON tbljobs USING btree (removed);


--
-- Name: tbljobs_idx_statusremoved; Type: INDEX; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE INDEX tbljobs_idx_statusremoved ON tbljobs USING btree (jobstatus, removed);


--
-- Name: tbljobs_index_jobstatus; Type: INDEX; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE INDEX tbljobs_index_jobstatus ON tbljobs USING btree (jobstatus);


--
-- Name: tbljobs_index_machine; Type: INDEX; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE INDEX tbljobs_index_machine ON tbljobs USING btree (machine);


--
-- Name: tbljobs_index_options; Type: INDEX; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE INDEX tbljobs_index_options ON tbljobs USING btree (options);


--
-- Name: tbljobs_index_revision; Type: INDEX; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE INDEX tbljobs_index_revision ON tbljobs USING btree (revision);


--
-- Name: tbljobs_index_userid; Type: INDEX; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE INDEX tbljobs_index_userid ON tbljobs USING btree (userid);


--
-- Name: tbljobs_index_version; Type: INDEX; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE INDEX tbljobs_index_version ON tbljobs USING btree (version);


--
-- Name: tblmachine_site; Type: INDEX; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE INDEX tblmachine_site ON tblmachines USING btree (site);


--
-- Name: tblmachines_leaseto; Type: INDEX; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE INDEX tblmachines_leaseto ON tblmachines USING btree (leaseto);


--
-- Name: tblresults_detailid; Type: INDEX; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE INDEX tblresults_detailid ON tblresults USING btree (detailid);


--
-- Name: tblresults_index_jobid; Type: INDEX; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE INDEX tblresults_index_jobid ON tblresults USING btree (jobid);


--
-- Name: tblresults_index_test; Type: INDEX; Schema: public; Owner: xenrtd; Tablespace: 
--

CREATE INDEX tblresults_index_test ON tblresults USING btree (test);


--
-- Name: public; Type: ACL; Schema: -; Owner: postgres
--

REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM postgres;
GRANT ALL ON SCHEMA public TO postgres;
GRANT ALL ON SCHEMA public TO PUBLIC;


--
-- Name: jobid_seq; Type: ACL; Schema: public; Owner: xenrtd
--

REVOKE ALL ON SEQUENCE jobid_seq FROM PUBLIC;
REVOKE ALL ON SEQUENCE jobid_seq FROM xenrtd;
GRANT ALL ON SEQUENCE jobid_seq TO xenrtd;
GRANT ALL ON SEQUENCE jobid_seq TO gxenrt;


--
-- Name: schedulelock; Type: ACL; Schema: public; Owner: xenrtd
--

REVOKE ALL ON TABLE schedulelock FROM PUBLIC;
REVOKE ALL ON TABLE schedulelock FROM xenrtd;
GRANT ALL ON TABLE schedulelock TO xenrtd;
GRANT ALL ON TABLE schedulelock TO gxenrt;
GRANT SELECT ON TABLE schedulelock TO qauser;


--
-- Name: serial; Type: ACL; Schema: public; Owner: xenrtd
--

REVOKE ALL ON SEQUENCE serial FROM PUBLIC;
REVOKE ALL ON SEQUENCE serial FROM xenrtd;
GRANT ALL ON SEQUENCE serial TO xenrtd;
GRANT ALL ON SEQUENCE serial TO gxenrt;


--
-- Name: tblallowedfailures; Type: ACL; Schema: public; Owner: xenrtd
--

REVOKE ALL ON TABLE tblallowedfailures FROM PUBLIC;
REVOKE ALL ON TABLE tblallowedfailures FROM xenrtd;
GRANT ALL ON TABLE tblallowedfailures TO xenrtd;
GRANT ALL ON TABLE tblallowedfailures TO gxenrt;
GRANT SELECT ON TABLE tblallowedfailures TO qauser;


--
-- Name: tblcasesets; Type: ACL; Schema: public; Owner: xenrtd
--

REVOKE ALL ON TABLE tblcasesets FROM PUBLIC;
REVOKE ALL ON TABLE tblcasesets FROM xenrtd;
GRANT ALL ON TABLE tblcasesets TO xenrtd;
GRANT ALL ON TABLE tblcasesets TO gxenrt;
GRANT SELECT ON TABLE tblcasesets TO qauser;


--
-- Name: tbldetails; Type: ACL; Schema: public; Owner: xenrtd
--

REVOKE ALL ON TABLE tbldetails FROM PUBLIC;
REVOKE ALL ON TABLE tbldetails FROM xenrtd;
GRANT ALL ON TABLE tbldetails TO xenrtd;
GRANT ALL ON TABLE tbldetails TO gxenrt;
GRANT SELECT ON TABLE tbldetails TO qauser;


--
-- Name: tblevents; Type: ACL; Schema: public; Owner: xenrtd
--

REVOKE ALL ON TABLE tblevents FROM PUBLIC;
REVOKE ALL ON TABLE tblevents FROM xenrtd;
GRANT ALL ON TABLE tblevents TO xenrtd;
GRANT ALL ON TABLE tblevents TO gxenrt;
GRANT SELECT ON TABLE tblevents TO qauser;


--
-- Name: tbljobdetails; Type: ACL; Schema: public; Owner: xenrtd
--

REVOKE ALL ON TABLE tbljobdetails FROM PUBLIC;
REVOKE ALL ON TABLE tbljobdetails FROM xenrtd;
GRANT ALL ON TABLE tbljobdetails TO xenrtd;
GRANT ALL ON TABLE tbljobdetails TO gxenrt;
GRANT SELECT ON TABLE tbljobdetails TO qauser;


--
-- Name: tbljobgroups; Type: ACL; Schema: public; Owner: xenrtd
--

REVOKE ALL ON TABLE tbljobgroups FROM PUBLIC;
REVOKE ALL ON TABLE tbljobgroups FROM xenrtd;
GRANT ALL ON TABLE tbljobgroups TO xenrtd;
GRANT ALL ON TABLE tbljobgroups TO gxenrt;
GRANT SELECT ON TABLE tbljobgroups TO qauser;


--
-- Name: tbljobs; Type: ACL; Schema: public; Owner: xenrtd
--

REVOKE ALL ON TABLE tbljobs FROM PUBLIC;
REVOKE ALL ON TABLE tbljobs FROM xenrtd;
GRANT ALL ON TABLE tbljobs TO xenrtd;
GRANT ALL ON TABLE tbljobs TO gxenrt;
GRANT SELECT ON TABLE tbljobs TO qauser;


--
-- Name: tblmachinedata; Type: ACL; Schema: public; Owner: xenrtd
--

REVOKE ALL ON TABLE tblmachinedata FROM PUBLIC;
REVOKE ALL ON TABLE tblmachinedata FROM xenrtd;
GRANT ALL ON TABLE tblmachinedata TO xenrtd;
GRANT ALL ON TABLE tblmachinedata TO gxenrt;
GRANT SELECT ON TABLE tblmachinedata TO qauser;


--
-- Name: tblmachines; Type: ACL; Schema: public; Owner: xenrtd
--

REVOKE ALL ON TABLE tblmachines FROM PUBLIC;
REVOKE ALL ON TABLE tblmachines FROM xenrtd;
GRANT ALL ON TABLE tblmachines TO xenrtd;
GRANT ALL ON TABLE tblmachines TO gxenrt;
GRANT SELECT ON TABLE tblmachines TO qauser;


--
-- Name: tblpatchman; Type: ACL; Schema: public; Owner: xenrtd
--

REVOKE ALL ON TABLE tblpatchman FROM PUBLIC;
REVOKE ALL ON TABLE tblpatchman FROM xenrtd;
GRANT ALL ON TABLE tblpatchman TO xenrtd;
GRANT ALL ON TABLE tblpatchman TO gxenrt;
GRANT SELECT ON TABLE tblpatchman TO qauser;


--
-- Name: tblperf; Type: ACL; Schema: public; Owner: xenrtd
--

REVOKE ALL ON TABLE tblperf FROM PUBLIC;
REVOKE ALL ON TABLE tblperf FROM xenrtd;
GRANT ALL ON TABLE tblperf TO xenrtd;
GRANT ALL ON TABLE tblperf TO gxenrt;
GRANT SELECT ON TABLE tblperf TO qauser;


--
-- Name: tblresults; Type: ACL; Schema: public; Owner: xenrtd
--

REVOKE ALL ON TABLE tblresults FROM PUBLIC;
REVOKE ALL ON TABLE tblresults FROM xenrtd;
GRANT ALL ON TABLE tblresults TO xenrtd;
GRANT ALL ON TABLE tblresults TO gxenrt;
GRANT SELECT ON TABLE tblresults TO qauser;


--
-- Name: tblresults_detailid_seq; Type: ACL; Schema: public; Owner: xenrtd
--

REVOKE ALL ON SEQUENCE tblresults_detailid_seq FROM PUBLIC;
REVOKE ALL ON SEQUENCE tblresults_detailid_seq FROM xenrtd;
GRANT ALL ON SEQUENCE tblresults_detailid_seq TO xenrtd;
GRANT ALL ON SEQUENCE tblresults_detailid_seq TO gxenrt;


--
-- Name: tblrevisions; Type: ACL; Schema: public; Owner: xenrtd
--

REVOKE ALL ON TABLE tblrevisions FROM PUBLIC;
REVOKE ALL ON TABLE tblrevisions FROM xenrtd;
GRANT ALL ON TABLE tblrevisions TO xenrtd;
GRANT ALL ON TABLE tblrevisions TO gxenrt;
GRANT SELECT ON TABLE tblrevisions TO qauser;


--
-- Name: tblsites; Type: ACL; Schema: public; Owner: xenrtd
--

REVOKE ALL ON TABLE tblsites FROM PUBLIC;
REVOKE ALL ON TABLE tblsites FROM xenrtd;
GRANT ALL ON TABLE tblsites TO xenrtd;
GRANT ALL ON TABLE tblsites TO gxenrt;
GRANT SELECT ON TABLE tblsites TO qauser;


--
-- Name: tblsubresults; Type: ACL; Schema: public; Owner: xenrtd
--

REVOKE ALL ON TABLE tblsubresults FROM PUBLIC;
REVOKE ALL ON TABLE tblsubresults FROM xenrtd;
GRANT ALL ON TABLE tblsubresults TO xenrtd;
GRANT ALL ON TABLE tblsubresults TO gxenrt;
GRANT SELECT ON TABLE tblsubresults TO qauser;


--
-- Name: tblsubresults_subid_seq; Type: ACL; Schema: public; Owner: xenrtd
--

REVOKE ALL ON SEQUENCE tblsubresults_subid_seq FROM PUBLIC;
REVOKE ALL ON SEQUENCE tblsubresults_subid_seq FROM xenrtd;
GRANT ALL ON SEQUENCE tblsubresults_subid_seq TO xenrtd;
GRANT ALL ON SEQUENCE tblsubresults_subid_seq TO gxenrt;


--
-- PostgreSQL database dump complete
--

