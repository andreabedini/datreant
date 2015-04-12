"""
The Bundle object is the primary manipulator for Containers in aggregate.
They are returned as queries to Groups, Coordinators, and other Bundles. They
offer convenience methods for dealing with many Containers at once.

"""
import os

import aggregators
import persistence
import filesystem
import mdsynthesis as mds

class _CollectionBase(object):
    """Common interface elements for ordered sets of Containers.

    :class:`aggregators.Members` and :class:`Bundle` both use this interface.

    """
    def add(self, *containers):
        """Add any number of members to this collection.

        :Arguments:
            *containers*
                Sims and/or Groups to be added; may be a list of Sims and/or
                Groups; Sims or Groups can be given as either objects or paths
                to directories that contain object statefiles
        """
        outconts = list()
        for container in containers:
            if isinstance(container, (list, tuple, Bundle, aggregators.Members)):
                self.add(*container)
            elif isinstance(container, mds.Container):
                outconts.append(container)
            elif os.path.exists(container):
                cont = filesystem.path2container(container)
                for c in cont:
                    outconts.append(c)

        for container in outconts:
            self.backend.add_member(container.uuid, container.name, container.containertype, container.location)

#TODO: use an in-memory SQLite db instead of a list for this?
class _BundleBackend():
    """Backend class for Bundle. 
    
    Has same interface as Group-specific components of
    :class:`persistence.GroupFile`. Behaves practically like an in-memory
    version of a state-file, but with only the components needed for the
    Bundle.

    """

    def __init__(self):
        # our table will be a list of dicts
        self.table = list()

    @File._write_state
    def add_member(self, uuid, name, containertype, location):
        """Add a member to the Group.

        If the member is already present, its location will be updated with
        the given location.

        :Arguments:
            *uuid*
                the uuid of the new member
            *containertype*
                the container type of the new member (Sim or Group)
            *location*
                location of the new member in the filesystem
    
        """
        # check if uuid already present
        index = [ self.table.index(item) for item in self.table if item['uuid'] == uuid ]
        if index:
            # if present, update location
            self.table[index]['abspath'] = os.path.abspath(location)
        else:
            newmem = {'uuid': uuid,
                      'name': name,
                      'containertype': containertype,
                      'abspath': os.path.abspath(location)}
                      
            self.table.append(newmem)

    @File._write_state
    def del_member(self, *uuid, **kwargs):
        """Remove a member from the Group.
    
        :Arguments:
            *uuid*
                the uuid(s) of the member(s) to remove

        :Keywords:
            *all*
                When True, remove all members [``False``]

        """
        table = self.handle.get_node('/', 'members')
        purge = kwargs.pop('all', False)

        if purge:
            table.remove()
            table = self.handle.create_table('/', 'members', self._Members, 'members')
            
        else:
            # remove redundant uuids from given list if present
            uuids = set([ str(uid) for uid in uuid ])

            # get matching rows
            #TODO: possibly faster to use table.where
            rowlist = list()
            for row in table:
                for uuid in uuids:
                    if (row['uuid'] == uuid):
                        rowlist.append(row.nrow)

            # must include a separate condition in case all rows will be removed
            # due to a limitation of PyTables
            if len(rowlist) == table.nrows:
                table.remove()
                table = self.handle.create_table('/', 'members', self._Members, 'members')
            else:
                rowlist.sort()
                j = 0
                # delete matching rows; have to use j to shift the register as we
                # delete rows
                for i in rowlist:
                    table.remove_row(i-j)
                    j=j+1

    @File._read_state
    def get_member(self, uuid):
        """Get all stored information on the specified member.
        
        Returns a dictionary whose keys are column names and values the
        corresponding values for the member.

        :Arguments:
            *uuid*
                uuid of the member to retrieve information for

        :Returns:
            *memberinfo*
                a dictionary containing all information stored for the
                specified member
        """
        table = self.handle.get_node('/', 'members')

        # check if uuid present
        rownum = [ row.nrow for row in table.where("uuid=='{}'".format(uuid)) ]
        if rownum:
            memberinfo = { x: table.colinstances[x][rownum[0]] for x in table.colinstances.keys() }
        else:
            self.logger.info('No such member in this Group.')
            memberinfo = None

        return memberinfo

    @File._read_state
    def get_members_uuid(self):
        """List uuid for each member.

        :Returns:
            *uuids*
                list giving uuids of all members, in order

        """
        table = self.handle.get_node('/', 'members')
        return [ x['uuid'] for x in table.iterrows() ]

    @File._read_state
    def get_members_name(self):
        """List name for each member.

        :Returns:
            *names*
                list giving names of all members, in order

        """
        table = self.handle.get_node('/', 'members')
        return [ x['name'] for x in table.iterrows() ]

    @File._read_state
    def get_members_containertype(self):
        """List containertype for each member.

        :Returns:
            *containertypes*
                list giving containertypes of all members, in order

        """
        table = self.handle.get_node('/', 'members')
        return [ x['containertype'] for x in table.iterrows() ]

    @File._read_state
    def get_members_location(self, path='abspath'):
        """List stored location for each member. 

        :Arguments:
            *path*
                type of paths to return; either absolute paths (abspath) or
                paths relative to the Group object (relGroup) ['abspath']

        :Returns:
            *locations*
                list giving locations of all members, in order

        """
        table = self.handle.get_node('/', 'members')
        return [ x[path] for x in table.iterrows() ]



class Bundle(object):
    """Non-persistent Container for Sims and Groups.
    
    A Bundle is basically an indexable set. It is often used to return the
    results of a query on a Coordinator or a Group, but can be used on its
    own as well.

    """
    def __init__(self, *containers, **kwargs):
        """Generate a Bundle from any number of Containers.
    
        :Arguments:
            *containers*
                list giving either Sims, Groups, or paths giving the
                directories of the state files for such objects in the
                filesystem
    
        :Keywords:
            *flatten* [NOT IMPLEMENTED]
                if ``True``, will recursively obtain members of any Groups;
                only Sims will be present in the bunch 
         
        """
        self.backend = _BundleBackend()

        self.add(*containers)

    #TODO: make more efficient by using ordered dict for storage?
    def add(self, *containers):
        outconts = list()
        for container in containers:
            if isinstance(container, list):
                self.add(*container)
            elif isinstance(container, mds.containers.Container):
                uuid = container.uuid
                if not (uuid in self._uuids):
                    outconts.append(container)
                    self._uuids.append(uuid)
            elif os.path.exists(container):
                conts = filesystem.path2container(container)
                for cont in conts:
                    uuid = cont.uuid
                    if not (uuid in self._uuids):
                        outconts.append(cont)
                        self._uuids.append(uuid)

        self._containers.extend(outconts)
    
    def _list(self):
        """Return list representation.
    
        """
        return list(self._containers)

    def __repr__(self):
        return "<Bundle({})>".format(self.list())

