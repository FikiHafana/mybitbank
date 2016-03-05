"""
The MIT License (MIT)

Copyright (c) 2016 Stratos Goudelis

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

"""

import calendar
import urllib2

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from mybitbank.libs import misc
from mybitbank.libs.config import MainConfig
from mybitbank.libs.connections import connector
from mybitbank.libs.entities import getWallets
from mybitbank.libs.events import Events


@login_required
def index(request):
    '''
    Handler for the dashboard main page
    '''
    currect_section = 'dashboard'
    
    # set the request in the connector object
    connector.request = request
    
    # get all wallets
    wallets = getWallets(connector)

    # more efficient if we do only one call
    transactions = []
    for wallet in wallets:
        transactions = transactions + wallet.listTransactions(5, 0)
    
    # sort result
    transactions = sorted(transactions, key=lambda k: k.get('time', 0), reverse=True)
    
    # get only 10 transactions
    transactions = transactions[0:5]

    # events
    list_of_events = Events.objects.all().order_by('-entered')[:5]  
    for single_event in list_of_events:
        timestamp = calendar.timegm(single_event.entered.timetuple())
        single_event.entered_pretty = misc.twitterizeDate(timestamp)
    
    page_title = "Dashboard"
    sections = misc.getSiteSections('dashboard')
    context = {
               'globals': MainConfig['globals'],
               'system_errors': connector.errors,
               'system_alerts': connector.alerts,
               'request': request,
               'breadcrumbs': misc.buildBreadcrumbs(currect_section),
               'page_title': page_title,
               'page_sections': sections,
               'wallets': wallets,
               'transactions': transactions,
               'events': list_of_events
               }
    return render(request, 'dashboard/index.html', context)

@login_required
@csrf_exempt
def proxy(request):
    '''
    Proxy script view for rates ticker APIs
    '''
    
    # set the request in the connector object
    connector.request = request
    
    if request.is_ajax():
        if request.method == 'POST':
            url = request.body
            #cache_hash = connector.getParamHash(url)
            #cache_object = connector.cache.fetch('rates', cache_hash)
            cache_object = False
            if cache_object:
                return HttpResponse(cache_object, content_type="application/json")
            else:
                opener = urllib2.build_opener()
                opener.addheaders = [('User-agent', "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.7; rv:25.0) Gecko/20100101 Firefox/25.0")]
                response = opener.open(url)
                rates_json = response.read()
                #connector.cache.store('rates', cache_hash, rates_json, 60)
                return HttpResponse(rates_json, content_type="application/json")
