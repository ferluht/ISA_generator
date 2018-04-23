import json
import logging
import re
from math import log2, log10

class ISAGenerator():

    ISA_output_padding = 50

    def __init__(self, input_desc_file='example_input.json'):

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

        self.logger.info('initialization start')

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
                if re.match('>=*', field[name]):
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

    def placeFormatAndOpcode(self):
        self.logger.info('placing format')
        for fmtcode, format in enumerate(self.formats):
            self.formats[format]['bitmask'] = [
                {
                    'name': 'F',
                    'msb': self.length - 1,
                    'lsb': int(self.length - log2(len(self.formats))),
                    'value': bin(fmtcode)[2:].zfill(self.length - int(self.length - log2(len(self.formats))))
                },
            ]
            if len(self.formats[format]['insns']) > 1:
                self.formats[format]['bitmask'].append({
                    'name': 'OPCODE',
                    'msb': self.formats[format]['bitmask'][-1]['lsb'] - 1,
                    'lsb': int(self.formats[format]['bitmask'][-1]['lsb'] - log2(len(self.formats[format]['insns']))),
                    'value': {}
                })
                opcode_length = self.formats[format]['bitmask'][-1]['msb'] - \
                                self.formats[format]['bitmask'][-1]['lsb'] + 1
                for opcode, cmd in enumerate(self.formats[format]['insns']):
                    self.formats[format]['bitmask'][-1]['value'][cmd] = bin(opcode)[2:].zfill(opcode_length)

    def placeField(self, field):
        self.logger.info('placing field {}'.format(field))

        positions = {}

        for format in self.formats:
            if field in self.formats[format]['operands']:

                positions[format] = {}

                def place(i, ix, value):
                    positions[format][i] = {'index': ix, 'valid': value}

                def checkPlacement(ix, amsb, alsb, bmsb, minlength):
                    for i in range(amsb, alsb - 1, -1): place(i, ix, False)

                    if alsb - bmsb >= minlength:
                        for i in range(alsb - 1, bmsb + minlength - 1, -1): place(i, ix, True)
                        for i in range(bmsb + minlength - 1, bmsb - 1, -1): place(i, ix, False)
                    else:
                        for i in range(alsb, bmsb - 1, -1): place(i, ix, False)

                for ix, (a1, a2) in enumerate(zip(self.formats[format]['bitmask'], self.formats[format]['bitmask'][1:])):
                    checkPlacement(ix + 1, a1['msb'], a1['lsb'], a2['msb'], self.fields[field]['min'])

                checkPlacement(len(self.formats[format]['bitmask']), self.formats[format]['bitmask'][-1]['msb'],
                               self.formats[format]['bitmask'][-1]['lsb'], -1, self.fields[field]['min'])

        msb = 0

        for ix in range(self.length - 1, -1, -1):
            if all(positions[position][ix]['valid'] == True for position in positions):
                msb = ix
                break

        for format in positions:
            ix = positions[format][msb]['index']
            self.formats[format]['bitmask'].insert(ix, {
                'name': field,
                'msb': msb,
                'lsb': msb - self.fields[field]['min'] + 1,
                'value': '+'
            })
            # if self.fields[field]['min'] == self.fields[field]['max']:
            #     self.formats[format]['bitmask'][ix]['lsb'] = self.formats[format]['bitmask'][-1]['msb'] - \
            #                                                  self.fields[field]['min'] + 1
            # else:
            #     self.formats[format]['bitmask'][ix]['lsb'] = self.formats[format]['bitmask'][-1]['msb'] - \
            #                                                  self.fields[field]['min'] + 1

    def generateISA(self):
        self.placeFormatAndOpcode()
        for field in sorted(self.fields.items(), key=lambda x: -x[1]['priority']):
            self.placeField(field[0])

    def printISA(self):
        isa_description = '\n' + '|'.rjust(self.ISA_output_padding)
        ix_padding = int(log10(self.length - 1) + 1)
        for i in range(self.length - 1, -1, -1): isa_description += str(i).ljust(ix_padding) + '|'
        isa_description += '\n'
        for format in self.formats:
            format_description = 'F={}, {}'.format(self.formats[format]['bitmask'][0]['value'], format)\
                                     .ljust(self.ISA_output_padding - 1) + '|'
            last_lsb = self.length
            for field in self.formats[format]['bitmask']:
                if last_lsb - field['msb'] - 1: format_description += ''.rjust((last_lsb - field['msb'] - 1)*(ix_padding+1) - 1) + '|'
                name = field['name'][:(field['msb'] - field['lsb'])*(ix_padding+1) - 1]
                format_description += name.ljust((field['msb'] - field['lsb'])*(ix_padding+1) - 1) + '|'
                last_lsb = field['lsb']
            isa_description += format_description + '\n'
        isa_description = 'generated ISA\n' + isa_description
        self.logger.info(isa_description)


isag = ISAGenerator()
isag.generateISA()
isag.printISA()