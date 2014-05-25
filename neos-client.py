#!/usr/bin/env python
import os
import sys
import getopt
import itertools
import xmlrpclib

script_name = os.path.basename(sys.argv[0])
NEOS_HOST = "www.neos-server.org"
NEOS_PORT = 3332
neos = xmlrpclib.Server("http://%s:%d" % (NEOS_HOST, NEOS_PORT))
client_string = "NEOS submission tool [https://github.com/wlxiong/neos-client]"


def usage():
    help_string = """\
usage: %s [options] model_file
       %s [options] command_file
       %s [options] -m model_file [-d data_file]
       %s [options] -r command_file
options:
       -m,--model model_file
       -d,--data data_file
       -r,--run command_file
       -g,--category category e.g. ip, nco
       -s,--solver solver e.g. gurobi, knitro
       -c,--comments "comments"
       -e,--email email_addr
       -l,--list-solvers
       -D,--dry-run
       -v,--verbose
       -h,--help"""
    print >> sys.stderr, help_string % tuple([script_name] * 4)


def read_recursively(filepath, backtrace=None):
    # print "read_recursively(%s, %s)" % (filepath, backtrace)
    if backtrace is None:
        backtrace = []
    if filepath in backtrace:
        raise Exception("Find a cycle in included files: %s - %s" % (filepath, backtrace))
    fin = open(filepath.strip(), 'r')
    lines = []
    for line in fin:
        stripped_line = line.strip()
        # print "line", line,
        if stripped_line and stripped_line[0] == '#':
            lines.append(line)
            continue
        try:
            command, argument = stripped_line.split(None, 1)
        except ValueError:
            lines.append(line)
            continue
        argument = argument[:-1] if argument[-1] == ';' else argument
        if command == 'include':
            head, _ = os.path.split(filepath)
            fullpath = os.path.join(head, argument.strip().strip('"'))
            # print command, fullpath
            included_lines = read_recursively(fullpath, backtrace + [filepath])
            lines.extend(included_lines)
        else:
            lines.append(line)
    return lines


def parse_commands(runpath, lines):
    modelpath = []
    datapath = []
    cmd_lines = []
    for line in lines:
        # print "line:", line,
        stripped_line = line.strip()
        if stripped_line and stripped_line[0] == '#':
            cmd_lines.append(line)
            continue
        try:
            command, argument = stripped_line.split(None, 1)
        except ValueError:
            cmd_lines.append(line)
            continue
        argument = argument[:-1] if argument[-1] == ';' else argument
        head, _ = os.path.split(runpath)
        fullpath = os.path.join(head, argument.strip().strip('"'))
        if command == 'model':
            modelpath.append(fullpath)
        elif command == 'data':
            datapath.append(fullpath)
        else:
            cmd_lines.append(line)
    return cmd_lines, modelpath, datapath


def send(xml, verbose=False):
    print >> sys.stderr, "Sending job to NEOS (%d bytes)" % len(xml)
    jobNumber, password = neos.submitJob(xml)
    print >> sys.stderr, "jobNumber = %d, password = %s" % (jobNumber, password)

    offset = 0
    status = "Waiting"
    while status == "Running" or status == "Waiting":
        print >> sys.stderr, status
        msg, offset = neos.getIntermediateResults(jobNumber, password, offset)
        if verbose:
            sys.stderr.write(msg.data)
        status = neos.getJobStatus(jobNumber, password)
    print >> sys.stderr, status
    result = neos.getFinalResults(jobNumber, password).data
    print result


template = """\
<document>
<category>%(category)s</category>
<solver>%(solver)s</solver>
<inputType>AMPL</inputType>
<client>%(client)s</client>
<priority>long</priority>
<email>%(email)s</email>

<model><![CDATA[%(model)s]]></model>
<data><![CDATA[%(data)s]]></data>
<commands><![CDATA[%(commands)s]]></commands>
<comments><![CDATA[%(comments)s]]></comments>

</document>
"""


def submit(runpath, modelpath, datapath, category, solver, email, comments, verbose=False, dry_run=False):
    if runpath is not None:
        if verbose:
            print >> sys.stderr, "Read commands: %s" % runpath
        cmd_lines = read_recursively(runpath)
        # print "command lines:", cmd_lines
        cmd_lines, modelpaths, datapaths = parse_commands(runpath, cmd_lines)
    else:
        cmd_lines = []
        modelpaths = [modelpath] if modelpath is not None else []
        datapaths = [datapath] if datapath is not None else []
    if verbose:
        if modelpaths:
            print >> sys.stderr, "Read models: %s" % ", ".join(modelpaths)
        if datapaths:
            print >> sys.stderr, "Read data: %s" % ", ".join(datapaths)
    mod_lines = reduce(lambda a, b: a + b, [read_recursively(mod) for mod in modelpaths], [])
    dat_lines = reduce(lambda a, b: a + b, [read_recursively(dat) for dat in datapaths], [])
    model = "".join(mod_lines)
    data = "".join(dat_lines)
    commands = "".join(cmd_lines)
    xml = template % {'category': category, 'solver': solver, 'email': email, 'client': client_string,
                      'comments': comments, 'model': model, 'data': data, 'commands': commands}
    if dry_run:
        print xml
    else:
        send(xml, verbose)


def list_solvers():
    solver_fullname = neos.listAllSolvers()
    ampl_solvers = []
    for fullname in sorted(solver_fullname):
        try:
            category, solver, lang = fullname.split(':', 2)
        except ValueError:
            continue
        if lang.upper() == 'AMPL':
            ampl_solvers.append((category, solver))
    category_fullname = neos.listCategories()
    for category, solvers in itertools.groupby(ampl_solvers, lambda s: s[0]):
        print "%s: %s" % (category, category_fullname.get(category, category))
        print " ", ", ".join([solver for _, solver in solvers])


def main():
    try:
        opts, args = getopt.getopt(sys.argv[1:], "m:d:r:s:g:e:c:lDvh",
                                   ["model=", "data=", "run=", "solver=", "category=", "email=", "comments=",
                                    "list-solvers", "dry-run", "verbose", "help"])
    except getopt.GetoptError as err:
        # print help information and exit:
        print >> sys.stderr, str(err)
        usage()
        sys.exit(1)

    verbose = False
    dry_run = False
    comments = ""
    category = None
    solver = None
    email = None
    model = None
    data = None
    run = None

    for o, a in opts:
        if o in ('-h', '--help'):
            usage()
            sys.exit()
        elif o in ('-v', '--verbose'):
            verbose = True
        elif o in ('-D', '--dry-run'):
            dry_run = True
        elif o in ('-r', '--run'):
            run = a
        elif o in ('-d', '--data'):
            data = a
        elif o in ('-m', '--model'):
            model = a
        elif o in ('-s', '--solver'):
            solver = a
        elif o in ('-g', '--category'):
            category = a
        elif o in ('-e', '--email'):
            email = a
        elif o in ('-c', '--comments'):
            comments = a
        elif o in ('-l', '--list-solvers'):
            list_solvers()
            sys.exit()

    if model is None and run is None:
        if len(args):
            _, ext = os.path.splitext(args[0])
            if ext == '.run':
                run = args[0]
            elif ext == '.mod':
                model = args[0]
            else:
                print >> sys.stderr, "%s: no input file ends with '.run' or '.mod'" % script_name
                sys.exit(2)
        else:
            print >> sys.stderr, "%s: no input file" % script_name
            sys.exit(3)
    if model is not None and run is not None:
        print >> sys.stderr, "%s: only one input file is needed:" % script_name, \
                             "model file (*.mod) or command file (*.run)"
        sys.exit(4)
    if solver is None:
        print >> sys.stderr, "%s: no solver specified" % script_name
        sys.exit(5)
    if category is None:
        print >> sys.stderr, "%s: no solver category specified" % script_name
        sys.exit(6)

    submit(run, model, data, category, solver, email, comments, verbose, dry_run)


if __name__ == "__main__":
    main()
