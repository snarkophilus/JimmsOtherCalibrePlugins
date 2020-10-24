#!/usr/bin/env python
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai
from __future__ import (unicode_literals, division, absolute_import,
                        print_function)

__license__   = 'GPL v3'
__copyright__ = '2011, Grant Drake <grant.drake@gmail.com>, 2020, Jim Miller'
__docformat__ = 'restructuredtext en'

import six
from six import text_type as unicode

import pprint
pp = pprint.PrettyPrinter(indent=4)

import sys
from collections import OrderedDict
from functools import partial
try:
    from PyQt5.Qt import QMenu, QToolButton, QInputDialog
except ImportError as e:
    from PyQt4.Qt import QMenu, QToolButton, QInputDialog

from calibre.gui2.actions import InterfaceAction
from calibre.constants import numeric_version as calibre_version

from calibre.gui2 import error_dialog
import calibre_plugins.view_manager.config as cfg
from calibre_plugins.view_manager.common_utils import (set_plugin_icon_resources, get_icon,
                                        create_menu_action_unique)

PLUGIN_ICONS = ['images/view_manager.png', 'images/sort_asc.png', 'images/sort_desc.png']

class ViewManagerAction(InterfaceAction):

    name = 'View Manager'
    # Create our top-level menu/toolbar action (text, icon_path, tooltip, keyboard shortcut)
    action_spec = ('View Manager', None, None, None)
    popup_type = QToolButton.InstantPopup
    action_type = 'current'

    def genesis(self):
        self.menu = QMenu(self.gui)

        self.menu_actions = []

        # Read the plugin icons and store for potential sharing with the config widget
        icon_resources = self.load_resources(PLUGIN_ICONS)
        set_plugin_icon_resources(self.name, icon_resources)

        # Assign our menu to this action and an icon
        self.qaction.setMenu(self.menu)
        self.qaction.setIcon(get_icon(PLUGIN_ICONS[0]))
        self.has_pin_view = False

    def initialization_complete(self):
        self.current_view = None
        if not self.check_switch_to_last_view_for_library():
            self.rebuild_menus()
        self.has_pin_view = hasattr(self.gui.library_view,'pin_view')

    def show_configuration(self):
        self.interface_action_base_plugin.do_user_config(self.gui)

    def library_changed(self, db):
        # We need to rebuild out menus when the library is changed, as each library
        # will have it's own set of views
        self.initialization_complete()

    def rebuild_menus(self):
        views = cfg.get_library_config(self.gui.current_db)[cfg.KEY_VIEWS]
        m = self.menu
        m.clear()

        for action in self.menu_actions:
            self.gui.keyboard.unregister_shortcut(action.calibre_shortcut_unique_name)
            # starting in calibre 2.10.0, actions are registers at
            # the top gui level for OSX' benefit.
            if calibre_version >= (2,10,0):
                self.gui.removeAction(action)
        self.menu_actions = []

        if len(views) > 0:
            has_checked_view = False
            for key in sorted(views.keys()):
                is_checked = self.current_view == key
                shortcut_name = 'Apply View: ' + key
                ac = create_menu_action_unique(self, m, key, shortcut_name=shortcut_name,
                                               triggered=partial(self.switch_view, key),
                                               is_checked=is_checked)
                self.menu_actions.append(ac)
                if is_checked:
                    has_checked_view = True
            m.addSeparator()
            save_ac = create_menu_action_unique(self, m, '&Save View Columns', 'column.png',
                                                  triggered=self.save_view)
            self.menu_actions.append(save_ac)
            save_sort_ac = create_menu_action_unique(self, m, '&Save View Sort', 'sort.png',
                                                  triggered=partial(self.save_view,save_sort=True))
            self.menu_actions.append(save_sort_ac)

            reapply_ac = create_menu_action_unique(self, m, 'Re-Apply Current View', 'edit-redo.png', shortcut_name='Re-Apply Current View',
                                                   triggered=partial(self.switch_view, self.current_view))
            self.menu_actions.append(reapply_ac)
            if not has_checked_view:
                save_ac.setEnabled(False)
                save_sort_ac.setEnabled(False)
                reapply_ac.setEnabled(False)

        new_ac = create_menu_action_unique(self, m, '&Create new View', 'plus.png',
                                                  triggered=partial(self.save_view,create=True))
        self.menu_actions.append(new_ac)

        new_ac = create_menu_action_unique(self, m, 'Next View', 'next.png', shortcut_name='Next View',
                                           triggered=self.next_view)
        self.menu_actions.append(new_ac)
        m.addSeparator()

        cfg_ac = create_menu_action_unique(self, m, _('&Customize plugin')+'...', 'config.png',
                                           triggered=self.show_configuration)
        self.menu_actions.append(cfg_ac)
        self.gui.keyboard.finalize()

    def check_switch_to_last_view_for_library(self):
        library_config = cfg.get_library_config(self.gui.current_db)
        if library_config.get(cfg.KEY_AUTO_APPLY_VIEW, False):
            view_to_apply = library_config.get(cfg.KEY_VIEW_TO_APPLY, cfg.LAST_VIEW_ITEM)
            if view_to_apply == cfg.LAST_VIEW_ITEM:
                last_view = library_config.get(cfg.KEY_LAST_VIEW, '')
                if last_view:
                    self.switch_view(library_config[cfg.KEY_LAST_VIEW])
                    return True
            else:
                self.switch_view(view_to_apply)
                return True
        return False

    def contruct_config_cols(self,key_columns,view_info,state):
        sizes = state['column_sizes']
        new_config_cols = []

        # Now need to identify the column widths for each column
        if key_columns in view_info:
            prev_col_sizes = dict(view_info[key_columns])
        else:
            prev_col_sizes = dict()
        # ordered columns list from col_id->position map.
        ordered_cols = sorted(state['column_positions'], key=state['column_positions'].get)# state['column_positions'].items().sort(key=lambda x: x[1])
        # filter out hidden columns.
        ordered_cols = [x for x in ordered_cols if x not in state['hidden_columns']]
        for col in ordered_cols:
            # I'm not sure under what circumstances the saved col size
            # would be needed, but the previous code fell back to it.
            # JM
            prev_size = prev_col_sizes.get(col,-1)
            new_config_cols.append((col, sizes.get(col, prev_size)))

        return new_config_cols

    def save_view(self,create=False,save_sort=False):
        if self.current_view is None and not create:
            return

        library_config = cfg.get_library_config(self.gui.current_db)
        views = library_config[cfg.KEY_VIEWS]
        new_view_name = None
        if create:
            new_view_name, ok = QInputDialog.getText(self.gui, 'Add new view',
                                                     'Enter a unique display name for this view:', text='Default')
            if not ok:
                # Operation cancelled
                return
            new_view_name = unicode(new_view_name).strip()
            # Verify it does not clash with any other views in the list
            for view_name in views.keys():
                if view_name.lower() == new_view_name.lower():
                    return error_dialog(self.gui, 'Add Failed', 'A view with the same name already exists', show=True)

            view_info = cfg.get_empty_view()
            if self.has_pin_view:
                view_info[cfg.KEY_APPLY_PIN_COLUMNS] = self.gui.library_view.pin_view.isVisible()
            views[new_view_name] = view_info
        else:
            view_info = views[self.current_view]

        save_sort = save_sort or create
        save_columns = not save_sort or create

        # print("pre-view_info:")
        # pp.pprint(view_info)

        state = self.gui.library_view.get_state()
        # print("state:")
        # pp.pprint(state)

        if save_sort:
            new_config_sort = []
            already_sorted = {}
            TF_map = { True:0, False:1 } # no idea why VM records asc/desc that way...
            for col, direct in state['sort_history']:
                if col not in already_sorted:
                    already_sorted[col] = direct
                    new_config_sort.append([unicode(col),TF_map[direct]])
            view_info[cfg.KEY_SORT] = new_config_sort

        if save_columns:
            if self.has_pin_view:
                view_info[cfg.KEY_APPLY_PIN_COLUMNS] = self.gui.library_view.pin_view.isVisible()

                # only save pin columns if apply *and* currently showing.
                if view_info.get(cfg.KEY_APPLY_PIN_COLUMNS,False) and self.gui.library_view.pin_view.isVisible():
                    pin_state = self.gui.library_view.pin_view.get_state()
                    # print("pin_state:")
                    # pp.pprint(pin_state)

                    new_config_cols = self.contruct_config_cols(cfg.KEY_PIN_COLUMNS,view_info,pin_state)
                    # Persist the updated pin view column info
                    view_info[cfg.KEY_PIN_COLUMNS] = new_config_cols

                    # Save splitter location
                    view_info[cfg.KEY_PIN_SPLITTER_STATE] = self.get_pin_splitter_state()

            new_config_cols = self.contruct_config_cols(cfg.KEY_COLUMNS,view_info,state)
            # Persist the updated view column info
            view_info[cfg.KEY_COLUMNS] = new_config_cols

        library_config[cfg.KEY_VIEWS] = views
        cfg.set_library_config(self.gui.current_db, library_config)

        # print("post-view_info:")
        # pp.pprint(view_info)
        if create:
            self.rebuild_menus()
            self.switch_view(new_view_name)

    def next_view(self):
        library_config = cfg.get_library_config(self.gui.current_db)
        views = library_config[cfg.KEY_VIEWS]
        keys = sorted(views.keys())
        if len(keys) == 0:
            return
        key = None
        # print("self.current_view:%s"%self.current_view)
        if self.current_view == None or self.current_view not in keys or self.current_view == keys[-1]:
            key = keys[0]
        else:
            key = keys[keys.index(self.current_view)+1]
        if key != None:
            self.switch_view(key)

    def switch_view(self, key):
        # print("switch_view(%s)"%key)
        library_config = cfg.get_library_config(self.gui.current_db)
        view_info = library_config[cfg.KEY_VIEWS][key]
        selected_ids = self.gui.library_view.get_selected_ids()

        # Persist this as the last selected view
        if library_config.get(cfg.KEY_LAST_VIEW, None) != key:
            library_config[cfg.KEY_LAST_VIEW] = key
            cfg.set_library_config(self.gui.current_db, library_config)

        if view_info.get(cfg.KEY_APPLY_VIRTLIB,False):
            self.apply_virtlib(view_info[cfg.KEY_VIRTLIB])

        if view_info[cfg.KEY_APPLY_RESTRICTION]:
            self.apply_restriction(view_info[cfg.KEY_RESTRICTION])

        if view_info[cfg.KEY_APPLY_SEARCH]:
            self.apply_search(view_info[cfg.KEY_SEARCH])

        self.apply_column_and_sort(view_info)

        self.gui.library_view.select_rows(selected_ids)
        if view_info.get(cfg.KEY_JUMP_TO_TOP,False):
            self.gui.library_view.scroll_to_row(0)
            self.gui.library_view.set_current_row(0)
        self.current_view = key
        self.rebuild_menus()

    def apply_virtlib(self, virtlib_name):
        self.gui.apply_virtual_library(virtlib_name)

    def apply_restriction(self, restriction_name):
        current = unicode(self.gui.search_restriction.currentText())
        if current == restriction_name:
            return
        self.gui.apply_named_search_restriction(restriction_name)

    def apply_search(self, search_name):
        if len(search_name) == 0:
            self.gui.search.clear()
        else:
            idx = self.gui.saved_search.findText(search_name)
            if idx != -1:
                self.gui.saved_search.setCurrentIndex(idx)
                self.gui.saved_search.saved_search_selected(search_name)

    def contruct_state_from_view_info(self, cfg_key, view_info):
        model = self.gui.library_view.model()
        colmap = list(model.column_map)
        config_cols = view_info[cfg_key]
        # Make sure our config contains only valid columns
        valid_cols = OrderedDict([(cname,width) for cname, width in config_cols if cname in colmap])
        if not valid_cols:
            valid_cols = OrderedDict([('title', -1)])
        config_cols = [cname for cname in valid_cols.keys()]
        hidden_cols = [c for c in colmap if c not in config_cols]
        if 'ondevice' in hidden_cols:
            hidden_cols.remove('ondevice')
        def col_key(x):
            return config_cols.index(x) if x in config_cols else sys.maxsize
        positions = {}
        for i, col in enumerate(sorted(model.column_map, key=col_key)):
            positions[col] = i
        resize_cols = dict([(cname, width) for cname, width in six.iteritems(valid_cols) if width > 0])

        state = {'hidden_columns': hidden_cols,
                 'column_positions': positions,
                 'column_sizes': resize_cols}

        return state

    def apply_column_and_sort(self, view_info):
        # print("apply view_info:")
        # pp.pprint(view_info)

        state = self.contruct_state_from_view_info(cfg.KEY_COLUMNS,view_info)
        # print("set state:")
        # pp.pprint(state)

        model = self.gui.library_view.model()
        colmap = list(model.column_map)
        # Now setup the sorting
        sort_cols = view_info[cfg.KEY_SORT]
        # Make sure our config contains only valid columns
        sort_cols = [(c, asc) for c, asc in sort_cols if c in colmap]
        sh = []
        for col, asc in sort_cols:
            sh.append((col, asc==0))
        # print("set sort history:")
        # pp.pprint(sh)
        state['sort_history'] = sh
        self.gui.library_view.apply_state(state,max_sort_levels=len(state['sort_history']))

        self.gui.library_view.save_state()

        if self.has_pin_view:
            self.set_pin_view(view_info.get(cfg.KEY_APPLY_PIN_COLUMNS,False))
            if view_info.get(cfg.KEY_APPLY_PIN_COLUMNS,False):
                if cfg.KEY_PIN_COLUMNS in view_info and view_info.get(cfg.KEY_APPLY_PIN_COLUMNS,False) and self.gui.library_view.pin_view.isVisible():
                    # actual columns:
                    pin_state = self.contruct_state_from_view_info(cfg.KEY_PIN_COLUMNS,view_info)
                    # print("set pin_state:")
                    # pp.pprint(pin_state)
                    self.gui.library_view.pin_view.apply_state(pin_state)
                    self.gui.library_view.pin_view.save_state()
                # set splitter location
                self.set_pin_splitter_state(view_info.get(cfg.KEY_PIN_SPLITTER_STATE,None))

    def set_pin_view(self, show=True):
        ## Need to call column_header_context_handler(action='split')
        ## -- which toggles -- to both change split and save it to
        ## gprefs.
        if self.gui.library_view.pin_view.isVisible() != show:
            self.gui.library_view.column_header_context_handler(action='split')

    def get_pin_splitter_state(self):
        if hasattr(self.gui.library_view.pin_view.splitter,'splitter_state'):
            # not added until Calibre 2.23.
            return self.gui.library_view.pin_view.splitter.splitter_state
        else:
            return bytearray(self.gui.library_view.pin_view.splitter.saveState())

    def set_pin_splitter_state(self, state):
        if hasattr(self.gui.library_view.pin_view.splitter,'splitter_state'):
            # not added until Calibre 2.23.
            self.gui.library_view.pin_view.splitter.splitter_state = state
        elif state:
            self.gui.library_view.pin_view.splitter.restoreState(state)
