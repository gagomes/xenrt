<?xml version="1.0" encoding="ISO-8859-1"?>
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">

<xsl:variable name="css">/data/mktree.css</xsl:variable>
<xsl:variable name="jscript">/data/xenrt.js</xsl:variable>

<xsl:variable name="arrow"><xsl:text>>>>&#160;</xsl:text></xsl:variable>

<xsl:template match="/">
  <xsl:document href="trace.htm">
    <html>
    <head>
      <title>XenRT Log Viewer</title>
      <link rel="stylesheet" href="{$css}"/>
      <script language="JavaScript" src="{$jscript}"/>
    </head>
    <body>
      <ul class="mktree" style="margin-left: 150px">
        <xsl:apply-templates select="trace/methodcall"/>
      </ul>
    </body>
    </html>
  </xsl:document>
</xsl:template>

<xsl:template name="leaf">
  <li class="liBullet">
    <xsl:call-template name="timestamp"/>
    <span class="bullet">&#160;</span>
    <span onClick="details(this, '{generate-id(.)}');" style="cursor: pointer;">
      <xsl:call-template name="rewrite"/>         
    </span>
    <div><xsl:call-template name="details"/></div>
  </li>
</xsl:template>

<xsl:template name="open">
  <li class="liOpen">
    <xsl:call-template name="timestamp"/>
    <span class="bullet" onClick="toggle(this, '{generate-id(.)}');">&#160;</span>
    <span onClick="details(this, '{generate-id(.)}');" style="cursor: pointer;">
      <xsl:call-template name="rewrite"/>    
    </span>
    <div><xsl:call-template name="details"/></div>
    <ul>
      <xsl:apply-templates select="calls"/>
    </ul>
  </li>
</xsl:template>

<xsl:template name="closed">
  <li class="liClosed">
    <xsl:call-template name="timestamp"/>
    <span class="bullet" onClick="toggle(this, '{generate-id(.)}');">&#160;</span>
    <span onClick="details(this, '{generate-id(.)}');" style="cursor: pointer;">
      <xsl:call-template name="rewrite"/> 
<!--      <xsl:text>:</xsl:text><xsl:value-of select="count(descendant::*[not(boolean(ancestor-or-self::*[name='execute' or name='execdom0' or name='log' or name='logverbose' or name='lookup' or name='setResult' or name='reason']))])"/> -->
    </span>
    <div><xsl:call-template name="details"/></div> 
    <ul>
      <xsl:document href="{generate-id(.)}_subtree.htm">
        <xsl:apply-templates select="calls"/>
      </xsl:document>     
      <div id="{generate-id(.)}_subtree"/>
    </ul>  
  </li>
</xsl:template>

<!--
This template constructs the log tree. There are three cases 
to consider:

  1.  If the current node makes no further calls then it should be
      represented as a leaf node.
  2.  If the subtree rooted at the current node contains nodes
      that should be exposed for triage then it should be 
      represented as a open node.
  3.  Otherwise the node should be a closed node.

-->
<xsl:template match="methodcall">
  <xsl:choose>
    <!-- Check for calls below this node in the tree.-->
    <xsl:when test="count(child::*/child::methodcall) > 0"> 
      <xsl:choose>
        <!--Expose interesting nodes.-->
        <xsl:when test="descendant-or-self::*[name='setResult']">
          <xsl:call-template name="open"/>  
        </xsl:when>
        <xsl:when test="descendant-or-self::*[name='reason']">
          <xsl:call-template name="open"/> 
        </xsl:when>
        <xsl:otherwise>
          <xsl:call-template name="closed"/> 
        </xsl:otherwise>
      </xsl:choose>
    </xsl:when>
    <xsl:otherwise>
      <xsl:call-template name="leaf"/>
    </xsl:otherwise> 
  </xsl:choose>
</xsl:template>

<xsl:template name="timestamp">
  <span class="timestamp">
    <xsl:value-of select="details/timestamp"/>
  </span>
</xsl:template>

<xsl:template name="details">
  <div id="{generate-id(.)}_details" class="hidedetails"/>
  <xsl:document href="{generate-id(.)}_details.htm">
    <table class="detailtable"> 
      <tr class="detailtr">
        <td class="detailtd">Filename</td>
        <td class="detailtd"><xsl:value-of select="details/filename"/></td>
      </tr>
      <tr class="detailtr">
        <td class="detailtd">Line Number</td>
        <td class="detailtd"><xsl:value-of select="details/linenumber"/></td>
      </tr>
      <tr class="detailtr">
        <td class="detailtd">Class</td>
        <td class="detailtd"><xsl:value-of select="details/class"/></td>
      </tr>
      <tr class="detailtr">
        <td class="detailtd">Thread</td>
        <td class="detailtd"><xsl:value-of select="details/thread"/></td>
      </tr>
      <tr class="detailtr">
        <td class="detailtd">Time</td>
        <td class="detailtd"><xsl:value-of select="details/timestamp"/></td>
      </tr>
      <xsl:for-each select="details/argument">
        <tr class="detailtr">
          <td class="detailtd">Argument</td>
          <td class="detailtd"><xsl:value-of select="."/></td>
        </tr>
      </xsl:for-each>
      <tr class="detailtr">
        <td class="detailtd">Result</td>
        <td class="detailtd"><xsl:value-of select="result"/></td>
      </tr>
    </table>
  </xsl:document>
</xsl:template>

<!--Specific rewrites follow after this point.-->

<xsl:template name="rewrite">
  <xsl:choose>
    <xsl:when test="name='__init__'">
      <span class="type init">NEW&#160;</span>
      <xsl:value-of select="details/class"/>
    </xsl:when>
    <xsl:when test="name='runTC'">
      <span>Test Case</span>
    </xsl:when>
    <xsl:otherwise>
      <xsl:value-of select="name"/>
    </xsl:otherwise>
  </xsl:choose>
</xsl:template>

<xsl:template match="methodcall[name='logverbose']">
  <li class="liBullet">
    <xsl:call-template name="timestamp"/>
    <span onClick="details(this, '{generate-id(.)}');" class="bullet type verboselog">LOG&#160;</span>
    <xsl:value-of select="details/argument"/>
    <div><xsl:call-template name="details"/></div>
  </li>
</xsl:template>

<xsl:template match="methodcall[name='log']">
  <li class="liBullet">
    <xsl:call-template name="timestamp"/>
    <span onClick="details(this, '{generate-id(.)}');" class="bullet type normallog">LOG&#160;</span>
    <xsl:value-of select="details/argument"/>
    <div><xsl:call-template name="details"/></div>
  </li>
</xsl:template>

<xsl:template match="methodcall[name='lookup']">
  <li class="liBullet">
    <xsl:call-template name="timestamp"/>
    <span onClick="details(this, '{generate-id(.)}');" class="bullet type lookup">LOOKUP&#160;</span>
    <xsl:value-of select="details/argument[1]"/>
    <div><xsl:call-template name="details"/></div>
    <span class="type lookup">&#160;<xsl:value-of select="$arrow"/></span>
    <xsl:choose>
      <xsl:when test="result=None">
        <xsl:value-of select="details/argument[2]"/>
      </xsl:when>
      <xsl:otherwise>
        <xsl:value-of select="result"/>
      </xsl:otherwise>
    </xsl:choose>
  </li>
</xsl:template>

<xsl:template match="methodcall[name='setResult']">
  <li class="liBullet">
    <xsl:call-template name="timestamp"/> 
    <xsl:choose>
      <xsl:when test="details/argument=2">
        <span onClick="details(this, '{generate-id(.)}');" class="bullet type fail">RESULT: FAIL</span>
      </xsl:when>
      <xsl:otherwise>
        <span onClick="details(this, '{generate-id(.)}');" class="bullet type pass">RESULT: PASS</span>
      </xsl:otherwise>
    </xsl:choose>
    <div><xsl:call-template name="details"/></div>
  </li>
</xsl:template>

<xsl:template match="methodcall[name='reason']">
  <li class="liBullet">
    <xsl:call-template name="timestamp"/>
    <span onClick="details(this, '{generate-id(.)}');" class="bullet type reason">REASON&#160;</span>
    <xsl:value-of select="details/argument[1]"/>
    <div><xsl:call-template name="details"/></div>
  </li>
</xsl:template>

<xsl:template match="methodcall[name='execute']">
  <li class="liBullet">
    <xsl:call-template name="timestamp"/>
    <span onClick="details(this, '{generate-id(.)}');" class="bullet type cli">CLI&#160;</span>
    <xsl:for-each select="details/argument">
      <xsl:value-of select="."/>&#160;
    </xsl:for-each>
    <div class="result">
      <span class="type cli"><xsl:value-of select="$arrow"/></span>
      <xsl:value-of select="result"/>
    </div>
    <div><xsl:call-template name="details"/></div>
  </li>
</xsl:template>

<xsl:template match="methodcall[name='execdom0']">
  <li class="liBullet">
    <xsl:call-template name="timestamp"/>
    <span onClick="details(this, '{generate-id(.)}');" class="bullet type ssh">SSH&#160;</span>
    <xsl:for-each select="details/argument">
      <xsl:value-of select="."/>&#160;
    </xsl:for-each>
    <div class="result">
      <span class="type ssh"><xsl:value-of select="$arrow"/></span>
      <xsl:value-of select="result"/>
    </div>
    <div><xsl:call-template name="details"/></div>
  </li>
</xsl:template>

</xsl:stylesheet>
