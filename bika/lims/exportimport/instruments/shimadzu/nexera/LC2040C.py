# This file is part of Bika LIMS
#
# Copyright 2011-2017 by it's authors.
# Some rights reserved. See LICENSE.txt, AUTHORS.txt.

""" Shimadzu HPLC-PDA Nexera-I LC2040C
"""
from DateTime import DateTime
from Products.Archetypes.event import ObjectInitializedEvent
from Products.CMFCore.utils import getToolByName
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from bika.lims import bikaMessageFactory as _
from bika.lims.utils import t
from bika.lims import logger
from bika.lims.browser import BrowserView
from bika.lims.idserver import renameAfterCreation
from bika.lims.utils import changeWorkflowState
from bika.lims.utils import tmpID
from bika.lims.exportimport.instruments.resultsimport import InstrumentCSVResultsFileParser,\
    AnalysisResultsImporter
from cStringIO import StringIO
from datetime import datetime
from operator import itemgetter
from plone.i18n.normalizer.interfaces import IIDNormalizer
from zope.component import getUtility
import csv
import json
import plone
import re
import zope
import zope.event
import traceback

title = "Shimadzu HPLC-PDA Nexera-I LC2040C"


def Import(context, request):
    """ Read Shimadzu HPLC-PDA Nexera-I LC2040C analysis results
    """
    form = request.form
    infile = form['file'][0] if isinstance(form['file'],list) else form['file']
    artoapply = form['artoapply']
    override = form['override']
    sample = form.get('sample', 'requestid')
    instrument = form.get('instrument', None)
    errors = []
    logs = []

    # Load the most suitable parser according to file extension/options/etc...
    parser = None
    if not hasattr(infile, 'filename'):
        errors.append(_("No file selected"))
    parser = TSVParser(infile)

    if parser:
        # Load the importer
        status = ['sample_received', 'attachment_due', 'to_be_verified']
        if artoapply == 'received':
            status = ['sample_received']
        elif artoapply == 'received_tobeverified':
            status = ['sample_received', 'attachment_due', 'to_be_verified']

        over = [False, False]
        if override == 'nooverride':
            over = [False, False]
        elif override == 'override':
            over = [True, False]
        elif override == 'overrideempty':
            over = [True, True]

        sam = ['getRequestID', 'getSampleID', 'getClientSampleID']
        if sample =='requestid':
            sam = ['getRequestID']
        if sample == 'sampleid':
            sam = ['getSampleID']
        elif sample == 'clientsid':
            sam = ['getClientSampleID']
        elif sample == 'sample_clientsid':
            sam = ['getSampleID', 'getClientSampleID']

        importer = LC2040C_Importer(parser=parser,
                                           context=context,
                                           idsearchcriteria=sam,
                                           allowed_ar_states=status,
                                           allowed_analysis_states=None,
                                           override=over,
                                           instrument_uid=instrument)
        tbex = ''
        try:
            importer.process()
        except:
            tbex = traceback.format_exc()
        errors = importer.errors
        logs = importer.logs
        warns = importer.warns
        if tbex:
            errors.append(tbex)

    results = {'errors': errors, 'log': logs, 'warns': warns}

    return json.dumps(results)


class TSVParser(InstrumentCSVResultsFileParser):

    def __init__(self, csv):
        InstrumentCSVResultsFileParser.__init__(self, csv)
        self._currentresultsheader = []
        self._currentanalysiskw = ''
        self._numline = 0

    def _parseline(self, line):
        return self.parse_TSVline(line)

    def parse_TSVline(self, line):
        """ Parses result lines
        """

        split_row = [token.strip() for token in line.split('\t')]
        _results = {'DefaultResult': 'Conc.',}

        # ID# 1
        if split_row[0] == 'ID#':
            return 0
        # Name	CBDV - cannabidivarin
        elif split_row[0] == 'Name':
            if split_row[1]:
                self._currentanalysiskw = split_row[1]
                return 0
            else:
                self.warn("Analysis Keyword not found or empty",
                          numline=self._numline, line=line)
        #	Data Filename	Sample Name	Sample ID	Sample Type	Level#
        elif 'Sample ID' in split_row:
            split_row.insert(0,'#')
            self._currentresultsheader = split_row
            return 0
        #1	QC PREP A_QC PREP A_009.lcd	QC PREP
        elif split_row[0].isdigit():
            _results.update(dict(zip(self._currentresultsheader, split_row)))

            # 10/17/2016 7:55:06 PM
            try:
                da = datetime.strptime(
                _results['Date Acquired'], "%m/%d/%Y %I:%M:%S %p")
                self._header['Output Date'] = da
                self._header['Output Time'] = da
            except ValueError:
                self.err("Invalid Output Time format",
                         numline=self._numline, line=line)
            self._addRawResult(_results['Sample ID'],
                               values={self._currentanalysiskw:_results},
                               override=False)

class LC2040C_Importer(AnalysisResultsImporter):

    def __init__(self, parser, context, idsearchcriteria, override,
                 allowed_ar_states=None, allowed_analysis_states=None,
                 instrument_uid=''):
        AnalysisResultsImporter.__init__(self, parser, context, idsearchcriteria,
                                         override, allowed_ar_states,
                                         allowed_analysis_states,
                                         instrument_uid)
