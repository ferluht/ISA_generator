import json
import logging
import re
import copy
from math import log2, log10

class ISAGenerator():

    ISA_output_padding = 50

    def __init__(self, input_desc_file='example_input.json', verbose=True):

        self.logger = logging.getLogger('ISAGenerator')
        self.logger.setLevel(logging.DEBUG)
        fh = logging.FileHandler('log')
        fh.setLevel(logging.DEBUG)
        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)
        self.logger.addHandler(fh)
        self.logger.addHandler(ch)

        self.verbose = verbose

        self.logger.info('initialization start')
        self.out_filename = 'output_' + input_desc_file

        try:
            self.input_desc = json.load(open(input_desc_file))
            self.parseLength()
            self.parseFields()
            self.parseInstructions()
            self.logger.info('loaded ISA description')
        except Exception as err:
            self.logger.error(str(err))
            raise IOError

        self.logger.info('initialization complete')

    def parseLength(self):
        self.logger.info('parsing length')
        self.length = int(self.input_desc['length'])

    def parseFields(self):
        self.logger.info('parsing fields')
        self.fields = {}

        for field in self.input_desc['fields']:
            for name in field:
                if re.match('>=*', str(field[name])):
                    self.fields[name] = {
                        'min': int(field[name][2:]),
                        'max': self.length
                    }
                else:
                    self.fields[name] = {
                        'min': int(field[name]),
                        'max': int(field[name])
                    }
                self.fields[name]['priority'] = 0

    def parseInstructions(self):
        self.logger.info('parsing instructions')
        self.formats = {}

        for format in self.input_desc['instructions']:
            self.formats[format['format']] = {
                'insns': format['insns'],
                'operands': format['operands'],
                'comment': format['comment']
            }
            for field in format['operands']:
                self.fields[field]['priority'] += 1

    def createField(self, name, msb, lsb, value):
        return { 'name': name, 'msb': msb, 'lsb': lsb, 'value': value }

    def placeFormatAndOpcode(self):
        self.logger.info('placing format and opcode')
        for fmtcode, format in enumerate(self.formats):
            self.formats[format]['bitmask'] = \
                [ self.createField(name='F', msb=self.length - 1, lsb=int(self.length - log2(len(self.formats))),
                    value=bin(fmtcode)[2:].zfill(self.length - int(self.length - log2(len(self.formats))))), ]

            if len(self.formats[format]['insns']) > 1:
                self.formats[format]['bitmask'].append(
                    self.createField(name='OPCODE', msb=self.formats[format]['bitmask'][-1]['lsb'] - 1,
                    lsb=int(self.formats[format]['bitmask'][-1]['lsb'] - log2(len(self.formats[format]['insns']))),
                    value={}))
                opcode_length = self.formats[format]['bitmask'][-1]['msb'] - self.formats[format]['bitmask'][-1]['lsb']
                for opcode, cmd in enumerate(self.formats[format]['insns']):
                    self.formats[format]['bitmask'][-1]['value'][cmd] = bin(opcode)[2:].zfill(opcode_length + 1)

    def placeReserved(self, formats):

        for format in formats:
            res = []
            offset = 0
            for ix, (a1, a2) in enumerate(zip(formats[format]['bitmask'], formats[format]['bitmask'][1:])):
                if a1['lsb'] - a2['msb'] > 1:
                    res.append((ix + offset, a1['lsb'], a2['msb']))
                    offset += 1

            if formats[format]['bitmask'][-1]['lsb']:
                res.append((len(formats[format]['bitmask']) + offset, formats[format]['bitmask'][-1]['lsb'], -1))
                offset += 1

            for r in res:
                formats[format]['bitmask'].insert(r[0] + 1, self.createField(
                    name='RESERVED', msb=r[1] - 1, lsb=r[2] + 1, value=''))

    def delReserved(self, formats):
        for format in formats:
            formats[format]['bitmask'] = [item for item in formats[format]['bitmask'] if item['name'] != 'RESERVED']

    def calcScore(self, formats):
        self.placeReserved(formats)
        used_bits = self.length*len(self.formats)
        for format in formats:
            for field in formats[format]['bitmask']:
                if field['name'] == 'RESERVED':
                    used_bits -= (field['msb'] - field['lsb'] + 1)
        if self.verbose: self.printISA(formats, 'generated ISA, score {}'.format(used_bits))
        if self.bestISA['used_bits'] < used_bits:
            self.bestISA['used_bits'] = used_bits
            self.bestISA['formats'] = copy.deepcopy(formats)
            self.dumpJson()
        self.delReserved(formats)

    def dumpJson(self):
        self.printISA(self.bestISA['formats'], 'BEST ISA FOUND:')
        output_json = []
        for format in self.bestISA['formats']:
            if len(self.bestISA['formats'][format]['insns']) > 1:
                for cmd in self.bestISA['formats'][format]['bitmask'][1]['value']:
                    output_json.append({
                        'insn': cmd,
                        'fields': copy.deepcopy(self.bestISA['formats'][format]['bitmask'])
                    })
                    output_json[-1]['fields'][1]['value'] = self.bestISA['formats'][format]['bitmask'][1]['value'][cmd]
            else:
                output_json.append({
                    'insn': self.bestISA['formats'][format]['insns'][0],
                    'fields': copy.deepcopy(self.bestISA['formats'][format]['bitmask'])
                })
        with open(self.out_filename, 'w') as outfile:
            json.dump(output_json, outfile, indent=4)

    def placeField(self, field, remain_fields, formats):

        if self.verbose: self.logger.info('placing field {}'.format(field))

        positions = {}

        for format in formats:
            if field in formats[format]['operands']:

                positions[format] = {}

                def place(i, ix, value):
                    positions[format][i] = {'index': ix, 'length': value}

                def checkPlacement(ix, amsb, alsb, bmsb, minlength):
                    for i in range(amsb, alsb - 1, -1): place(i, ix, 0)

                    if alsb - bmsb >= minlength:
                        for i in range(alsb - 1, bmsb + minlength - 1, -1): place(i, ix, i - bmsb)
                        for i in range(bmsb + minlength - 1, bmsb - 1, -1): place(i, ix, 0)
                    else:
                        for i in range(alsb, bmsb - 1, -1): place(i, ix, 0)

                for ix, (a1, a2) in enumerate(zip(formats[format]['bitmask'], formats[format]['bitmask'][1:])):
                    checkPlacement(ix + 1, a1['msb'], a1['lsb'], a2['msb'], self.fields[field]['min'])

                checkPlacement(len(formats[format]['bitmask']), formats[format]['bitmask'][-1]['msb'],
                               formats[format]['bitmask'][-1]['lsb'], -1, self.fields[field]['min'])

        for ix in range(self.length - 1, -1, -1):
            if all(positions[position][ix]['length'] > 0 for position in positions):
                length = min(positions[position][ix]['length'] for position in positions)
                msb = ix
                for l in range(self.fields[field]['min'], self.fields[field]['max'] + 1):
                    if l <= length:
                        for format in positions:
                            ix = positions[format][msb]['index']
                            formats[format]['bitmask'].insert(ix, self.createField(name=field, msb=msb,
                                                                                   lsb=msb - l + 1, value='+'))
                        self.placeField(remain_fields[0][0], remain_fields[1:], formats) \
                            if len(remain_fields) else self.calcScore(formats)
                        for format in positions:
                            formats[format]['bitmask'] = [item for item in formats[format]['bitmask'] if item['name'] != field]

    def generateISA(self):
        self.logger.info('start finding ISA')
        self.bestISA = {'used_bits': 0, 'formats': {}}
        self.placeFormatAndOpcode()
        sorted_fields = sorted(self.fields.items(), key=lambda x: -x[1]['priority'])
        self.placeField(sorted_fields[0][0], sorted_fields[1:], self.formats)

        self.dumpJson()

    def printISA(self, formats, msg):
        isa_description = '\n' + '|'.rjust(self.ISA_output_padding)
        ix_padding = int(log10(self.length - 1) + 1)
        for i in range(self.length - 1, -1, -1): isa_description += str(i).ljust(ix_padding) + '|'
        isa_description += '\n'
        for format in formats:
            format_description = 'F={}, {}'.format(formats[format]['bitmask'][0]['value'], format)\
                                     .ljust(self.ISA_output_padding - 1) + '|'
            for field in formats[format]['bitmask']:
                name = field['name'][:(field['msb'] - field['lsb'] + 1)*(ix_padding+1) - 1]
                format_description += name.ljust((field['msb'] - field['lsb'] + 1)*(ix_padding+1) - 1) + '|'
            isa_description += format_description + '\n'
        isa_description = msg + '\n' + isa_description
        self.logger.info(isa_description)


isag = ISAGenerator(input_desc_file='03.json', verbose=False)
ISA = isag.generateISA()