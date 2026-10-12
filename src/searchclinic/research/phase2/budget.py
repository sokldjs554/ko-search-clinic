"""Offline reservation guard. No key handling, transport or API calls."""
from decimal import Decimal


class CallBudget:
    def __init__(self, model, input_usd_million, output_usd_million, max_calls, usd_limit, approved=False):
        self.model = model
        self.input_price, self.output_price = Decimal(input_usd_million), Decimal(output_usd_million)
        self.usd_limit = Decimal(usd_limit)
        if (not model or type(max_calls) is not int or max_calls<1 or any(
                not x.is_finite() or x<=0 for x in (self.input_price,self.output_price,self.usd_limit))):
            raise ValueError('known positive model prices and budget required')
        self.max_calls, self.approved = max_calls, approved
        self.spent = self.reserved = Decimal(0)
        self.calls, self.halted, self.entries = 0, False, {}

    def cost(self, inputs, outputs):
        return (self.input_price*inputs+self.output_price*outputs)/Decimal(1000000)

    def reserve(self, query_id, input_bound):
        if not self.approved:
            raise PermissionError('separate paid-experiment approval required')
        if self.halted:
            raise ValueError('budget halted')
        if query_id in self.entries:
            raise ValueError('query retry forbidden')
        if self.calls >= self.max_calls:
            raise ValueError('maximum calls reached')
        if type(input_bound) is not int or not 0<=input_bound<=6000:
            raise ValueError('verified input token bound required, cap 6000')
        amount = self.cost(input_bound,1500)
        if self.spent+self.reserved+amount > self.usd_limit:
            raise ValueError('USD reservation limit exceeded')
        self.entries[query_id]={'reserved':amount,'input_bound':input_bound,'status':'reserved'}
        self.reserved+=amount
        self.calls+=1
        return amount

    def settle(self, query_id, inputs, outputs, model):
        entry=self.entries[query_id]
        if self.halted or entry['status']!='reserved':
            raise ValueError('halted or already settled')
        if model!=self.model:
            self.halted=True
            raise ValueError('model substitution forbidden')
        if (type(inputs) is not int or type(outputs) is not int or
                not 0<=inputs<=entry['input_bound'] or not 0<=outputs<=1500):
            self.halted=True
            raise ValueError('unknown or overcap usage; reservation retained')
        self.reserved-=entry['reserved']
        self.spent+=self.cost(inputs,outputs)
        entry.update(status='settled',inputs=inputs,outputs=outputs)

    def fail(self, query_id, reason):
        entry=self.entries[query_id]
        if entry['status']!='reserved':
            raise ValueError('call not pending')
        entry.update(status='error',error=reason)
        self.halted=True
